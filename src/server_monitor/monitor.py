"""Core monitoring daemon implementation."""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Dict, List, Optional

import structlog

from .checks import BaseCheck, create_check
from .config import EndpointConfig, MonitorConfig
from .database import CheckStatus, DatabaseManager
from .notifications import NotificationContext, create_notification_manager

logger = structlog.get_logger(__name__)


class EndpointMonitor:
    """Monitor for a single endpoint."""

    def __init__(
        self,
        config: EndpointConfig,
        db_manager: DatabaseManager,
        global_config: MonitorConfig,
    ):
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
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start monitoring this endpoint."""
        if self._task and not self._task.done():
            logger.warning("Monitor already running", endpoint=self.config.name)
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Started monitoring", endpoint=self.config.name)

    async def stop(self) -> None:
        """Stop monitoring this endpoint."""
        self._stop_event.set()
        if self._task and not self._task.done():
            await self._task
        logger.info("Stopped monitoring", endpoint=self.config.name)

    async def _monitor_loop(self) -> None:
        """Main monitoring loop for this endpoint."""
        while not self._stop_event.is_set():
            try:
                # Execute check
                result = await self.check.execute()

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
                    failure_count = previous_status_data.get("failure_count", 0)

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
            except asyncio.TimeoutError:
                # Timeout is expected, continue to next check
                continue


class MonitorDaemon:
    """Main monitoring daemon that manages all endpoint monitors."""

    def __init__(self, config: MonitorConfig):
        self.config = config
        self.db_manager = DatabaseManager(config.global_config.database)
        self.endpoint_monitors: Dict[str, EndpointMonitor] = {}
        self._shutdown_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(config.global_config.max_concurrent_checks)

    async def initialize(self) -> None:
        """Initialize the daemon."""
        # Initialize database
        await self.db_manager.initialize()

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

        # Start all endpoint monitors
        start_tasks = []
        for monitor in self.endpoint_monitors.values():
            start_tasks.append(monitor.start())

        await asyncio.gather(*start_tasks)

        logger.info(
            "Monitoring daemon started", endpoints=list(self.endpoint_monitors.keys())
        )

        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Stop the monitoring daemon."""
        logger.info("Stopping monitoring daemon...")

        # Stop all endpoint monitors
        stop_tasks = []
        for monitor in self.endpoint_monitors.values():
            stop_tasks.append(monitor.stop())

        await asyncio.gather(*stop_tasks, return_exceptions=True)

        # Close database connections
        await self.db_manager.close()

        logger.info("Monitoring daemon stopped")

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(signum: int, frame) -> None:
            logger.info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self._shutdown())

        # Only set up signal handlers on Unix systems
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)

    async def _shutdown(self) -> None:
        """Initiate graceful shutdown."""
        self._shutdown_event.set()

    async def get_status(self) -> Dict[str, any]:
        """Get current status of all endpoints."""
        status = {
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
        stop_tasks = []
        for monitor in self.endpoint_monitors.values():
            stop_tasks.append(monitor.stop())

        await asyncio.gather(*stop_tasks, return_exceptions=True)

        # Clear current monitors
        self.endpoint_monitors.clear()

        # Update configuration
        self.config = new_config

        # Reinitialize with new config
        await self.initialize()

        # Start monitors with new configuration
        start_tasks = []
        for monitor in self.endpoint_monitors.values():
            start_tasks.append(monitor.start())

        await asyncio.gather(*start_tasks)
