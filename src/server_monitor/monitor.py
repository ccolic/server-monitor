"""Core monitoring daemon implementation."""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any

# Handle TimeoutError compatibility across Python versions
# In Python 3.10+, asyncio.TimeoutError is an alias for TimeoutError
# In Python 3.8/3.9, they are different classes
try:
    # Test if asyncio.TimeoutError is the same as TimeoutError (Python 3.10+)
    if asyncio.TimeoutError is TimeoutError:
        AsyncTimeoutError = TimeoutError
    else:
        # Python 3.8/3.9 - they are different
        AsyncTimeoutError = asyncio.TimeoutError
except AttributeError:
    # Fallback for very old versions
    AsyncTimeoutError = asyncio.TimeoutError

import structlog

from .checks import create_check
from .config import EndpointConfig, MonitorConfig
from .database import CheckStatus, DatabaseManager
from .health import HealthCheckServer
from .notifications import NotificationContext, create_notification_manager

logger = structlog.get_logger(__name__)


class EndpointMonitor:
    """Monitor for a single endpoint.

    This class handles the monitoring of a single endpoint, including executing checks,
    storing results in the database, and sending notifications based on the check results.

    Attributes:
        config (EndpointConfig): Configuration for the endpoint.
        db_manager (DatabaseManager): Database manager for storing check results.
        global_config (MonitorConfig): Global configuration for the monitor.
        check: The check instance for the endpoint.
        notification_manager: Manager for sending notifications.
        _task (asyncio.Task | None): The asyncio task for the monitoring loop.
        _stop_event (asyncio.Event): Event to signal stopping the monitoring loop.
    """

    def __init__(
        self,
        config: EndpointConfig,
        db_manager: DatabaseManager,
        global_config: MonitorConfig,
    ) -> None:
        self.config = config
        self.db_manager = db_manager
        self.global_config = global_config
        self.check = create_check(config)
        self.notification_manager = create_notification_manager(
            global_email_config=global_config.global_config.email_notifications,
            global_webhook_config=global_config.global_config.webhook_notifications,
            endpoint_email_config=config.email_notifications,
            endpoint_webhook_config=config.webhook_notifications,
        )
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start monitoring this endpoint.

        This method initializes the monitoring loop for the endpoint and starts
        the asyncio task to execute checks periodically.

        Logs a warning if the monitor is already running.
        """
        if self._task and not self._task.done():
            logger.warning("Monitor already running", endpoint=self.config.name)
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Started monitoring", endpoint=self.config.name)

    async def stop(self) -> None:
        """Stop monitoring this endpoint.

        This method signals the monitoring loop to stop and waits for the
        asyncio task to complete.

        Logs an info message when monitoring is stopped.
        """
        self._stop_event.set()
        if self._task and not self._task.done():
            await self._task
        logger.info("Stopped monitoring", endpoint=self.config.name)

    async def _monitor_loop(self) -> None:
        """Main monitoring loop for this endpoint.

        This loop executes checks periodically, stores the results in the database,
        and sends notifications based on the check results and previous status.

        Handles exceptions and logs errors encountered during the loop.
        """
        while not self._stop_event.is_set():
            try:
                # Execute check with metrics tracking
                from .metrics import metrics

                async with metrics.measure_check(self.config.name):
                    result = await self.check.execute()

                # Record error in metrics if check failed
                if result.status != CheckStatus.SUCCESS:
                    metrics.record_error(self.config.name)

                # Get previous status for notification context
                previous_status_data = await self.db_manager.get_endpoint_status(
                    self.config.name
                )
                previous_status = None
                failure_count = 0

                if previous_status_data:
                    previous_status = CheckStatus(
                        previous_status_data["current_status"]
                    )
                    failure_count = int(previous_status_data.get("failure_count", 0))

                # Store result in database
                await self.db_manager.store_result(result)

                # Send notifications if needed
                context = NotificationContext(
                    result=result,
                    previous_status=previous_status,
                    failure_count=failure_count,
                )

                await self.notification_manager.send_notifications(context)

                logger.debug(
                    "Check completed",
                    endpoint=self.config.name,
                    status=result.status,
                    response_time=result.response_time,
                )

            except Exception as e:
                logger.error(
                    "Error in monitor loop", endpoint=self.config.name, error=str(e)
                )

            # Wait for next check interval
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.config.interval
                )
                # If we reach here, stop event was set
                break
            except AsyncTimeoutError:
                # Timeout is expected, continue to next check
                # Check again if stop event was set (helpful for fast shutdown)
                if self._stop_event.is_set():
                    break
                continue


class MonitorDaemon:
    """Main monitoring daemon that manages all endpoint monitors."""

    def __init__(self, config: MonitorConfig, health_port: int = 8080) -> None:
        self.config = config
        self.db_manager = DatabaseManager(config.global_config.database)
        self.health_server = HealthCheckServer(health_port)
        self.endpoint_monitors: dict[str, EndpointMonitor] = {}
        self._shutdown_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(config.global_config.max_concurrent_checks)
        self._shutdown_in_progress = False
        self._interrupt_count = 0
        self._shutdown_timeout = 5.0  # seconds
        self._original_sigterm_handler: Any = None
        self._original_sigint_handler: Any = None

    async def initialize(self) -> None:
        """Initialize the daemon."""
        # Initialize database
        await self.db_manager.initialize()

        # Set daemon reference in health server so it can get real status
        self.health_server.set_daemon(self)

        # Create endpoint monitors
        for endpoint_config in self.config.endpoints:
            if endpoint_config.enabled:
                monitor = EndpointMonitor(
                    config=endpoint_config,
                    db_manager=self.db_manager,
                    global_config=self.config,
                )
                self.endpoint_monitors[endpoint_config.name] = monitor

        logger.info(
            "Daemon initialized",
            total_endpoints=len(self.config.endpoints),
            enabled_endpoints=len(self.endpoint_monitors),
        )

    async def start(self) -> None:
        """Start the monitoring daemon."""
        if not self.endpoint_monitors:
            logger.warning("No enabled endpoints to monitor")
            return

        # Set up signal handlers for graceful shutdown
        self._setup_signal_handlers()

        # Start health check server
        await self.health_server.start()
        logger.info("Health check server started", port=self.health_server.port)

        # Start all endpoint monitors
        start_tasks: list[asyncio.Task[Any]] = []
        for monitor in self.endpoint_monitors.values():
            start_tasks.append(asyncio.create_task(monitor.start()))

        await asyncio.gather(*start_tasks)

        logger.info(
            "Monitoring daemon started", endpoints=list(self.endpoint_monitors.keys())
        )

        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Stop the monitoring daemon."""
        logger.info("Stopping monitoring daemon...")

        # Restore original signal handlers
        self._restore_signal_handlers()

        # Stop health check server
        try:
            await self.health_server.stop()
            logger.info("Health check server stopped")
        except Exception as e:
            logger.warning("Error stopping health check server", error=str(e))

        # Stop all endpoint monitors with timeout
        stop_tasks: list[asyncio.Task[Any]] = []
        for monitor in self.endpoint_monitors.values():
            stop_tasks.append(asyncio.create_task(monitor.stop()))

        try:
            # Implement a timeout for the cleanup tasks
            await asyncio.wait_for(
                asyncio.gather(*stop_tasks, return_exceptions=True),
                timeout=self._shutdown_timeout,
            )
        except AsyncTimeoutError:
            logger.warning(f"Clean shutdown timed out after {self._shutdown_timeout}s")

        try:
            # Close database connections with timeout
            await asyncio.wait_for(self.db_manager.close(), timeout=2.0)
        except AsyncTimeoutError:
            logger.warning("Database close operation timed out")

        logger.info("Monitoring daemon stopped")

    def _restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        if sys.platform != "win32":
            if self._original_sigterm_handler is not None:
                signal.signal(signal.SIGTERM, self._original_sigterm_handler)
                self._original_sigterm_handler = None
            if self._original_sigint_handler is not None:
                signal.signal(signal.SIGINT, self._original_sigint_handler)
                self._original_sigint_handler = None

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(signum: int, frame: Any) -> None:
            self._interrupt_count += 1

            if self._interrupt_count == 1:
                logger.info(
                    f"Received signal {signum}, initiating graceful shutdown..."
                )
                # Check if we have a running event loop before creating task
                try:
                    loop = asyncio.get_running_loop()
                    if not loop.is_closed():
                        asyncio.create_task(self._shutdown(graceful=True))
                except RuntimeError:
                    # No running event loop, set shutdown event directly
                    self._shutdown_event.set()
            elif self._interrupt_count == 2:
                logger.warning("Second interrupt received, expediting shutdown...")
                try:
                    loop = asyncio.get_running_loop()
                    if not loop.is_closed():
                        asyncio.create_task(self._shutdown(graceful=False))
                except RuntimeError:
                    # No running event loop, force exit
                    sys.exit(130)
            else:
                logger.warning("Multiple interrupts received, forcing exit...")
                # Force exit immediately on third Ctrl+C
                sys.exit(130)  # 130 is the exit code for SIGINT

        # Only set up signal handlers on Unix systems
        if sys.platform != "win32":
            # Store original handlers before replacing them
            self._original_sigterm_handler = signal.signal(
                signal.SIGTERM, signal_handler
            )
            self._original_sigint_handler = signal.signal(signal.SIGINT, signal_handler)

    async def _shutdown(self, graceful: bool = True) -> None:
        """Initiate shutdown.

        Args:
            graceful: If True, perform a graceful shutdown. If False, expedite shutdown.
        """
        if self._shutdown_in_progress:
            return

        self._shutdown_in_progress = True
        self._shutdown_event.set()

        if not graceful:
            # Expedited shutdown - don't wait for clean stop
            logger.warning("Performing expedited shutdown...")
            # Force exit after a short delay
            asyncio.get_event_loop().call_later(0.5, sys.exit, 130)

    async def get_status(self) -> dict[str, Any]:
        """Get current status of all endpoints."""
        status: dict[str, dict[str, Any]] = {
            "daemon": {
                "running": not self._shutdown_event.is_set(),
                "total_endpoints": len(self.config.endpoints),
                "active_monitors": len(self.endpoint_monitors),
            },
            "endpoints": {},
        }

        # Get status for each endpoint
        for endpoint_name, monitor in self.endpoint_monitors.items():
            endpoint_status = await self.db_manager.get_endpoint_status(endpoint_name)
            status["endpoints"][endpoint_name] = {
                "config": {
                    "type": monitor.config.type.value,
                    "interval": monitor.config.interval,
                    "enabled": monitor.config.enabled,
                },
                "status": endpoint_status,
            }

        return status

    async def reload_config(self, new_config: MonitorConfig) -> None:
        """Reload configuration and restart affected monitors."""
        logger.info("Reloading configuration...")

        # Stop all current monitors
        reload_stop_tasks: list[asyncio.Task[Any]] = []
        for monitor in self.endpoint_monitors.values():
            reload_stop_tasks.append(asyncio.create_task(monitor.stop()))

        await asyncio.gather(*reload_stop_tasks, return_exceptions=True)

        # Clear current monitors
        self.endpoint_monitors.clear()

        # Update configuration
        self.config = new_config

        # Reinitialize with new config
        await self.initialize()

        # Start monitors with new configuration
        reload_start_tasks: list[asyncio.Task[Any]] = []
        for monitor in self.endpoint_monitors.values():
            reload_start_tasks.append(asyncio.create_task(monitor.start()))

        await asyncio.gather(*reload_start_tasks)
