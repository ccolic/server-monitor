"""Health check endpoint for monitoring the monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from .metrics import metrics

if TYPE_CHECKING:
    from .monitor import MonitorDaemon


class HealthCheckServer:
    """Simple health check HTTP server."""

    def __init__(self, port: int = 8080) -> None:
        self.port = port
        self.app = web.Application()
        self._daemon: MonitorDaemon | None = None
        self._setup_routes()

    def set_daemon(self, daemon: MonitorDaemon) -> None:
        """Set the daemon reference for status endpoint."""
        self._daemon = daemon

    def _setup_routes(self) -> None:
        """Set up HTTP routes."""
        self.app.router.add_get("/health", self.health_check)
        self.app.router.add_get("/metrics", self.get_prometheus_metrics)
        self.app.router.add_get("/status", self.get_status)

    async def health_check(self, request: web.Request) -> web.Response:
        """Simple health check endpoint."""
        return web.json_response(
            {"status": "healthy", "timestamp": metrics.last_reset.isoformat()}
        )

    async def get_prometheus_metrics(self, request: web.Request) -> web.Response:
        """Get performance metrics in Prometheus format."""
        prometheus_data = metrics.get_prometheus_metrics()
        # Split content type to remove charset for aiohttp compatibility
        content_type = metrics.get_prometheus_content_type().split(";")[0]
        return web.Response(
            text=prometheus_data, content_type=content_type, charset="utf-8"
        )

    async def get_status(self, request: web.Request) -> web.Response:
        """Get detailed status information."""
        if self._daemon:
            try:
                status = await self._daemon.get_status()
            except Exception as e:
                # Fallback if daemon status fails
                status = {
                    "daemon": {"running": True, "error": str(e)},
                    "endpoints": {},
                }
        else:
            # Default status when daemon is not set
            status = {
                "daemon": {"running": True},
                "endpoints": {},
            }
        return web.json_response(status)

    async def start(self) -> None:
        """Start the health check server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()

    async def stop(self) -> None:
        """Stop the health check server."""
        if hasattr(self, "runner") and self.runner:
            await self.runner.cleanup()
