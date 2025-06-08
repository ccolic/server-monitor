"""Health check endpoint for monitoring the monitor."""

from __future__ import annotations

from aiohttp import web

from .metrics import metrics


class HealthCheckServer:
    """Simple health check HTTP server."""

    def __init__(self, port: int = 8080) -> None:
        self.port = port
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up HTTP routes."""
        self.app.router.add_get("/health", self.health_check)
        self.app.router.add_get("/metrics", self.get_metrics)
        self.app.router.add_get("/status", self.get_status)

    async def health_check(self, request: web.Request) -> web.Response:
        """Simple health check endpoint."""
        return web.json_response(
            {"status": "healthy", "timestamp": metrics.last_reset.isoformat()}
        )

    async def get_metrics(self, request: web.Request) -> web.Response:
        """Get performance metrics."""
        return web.json_response(metrics.get_metrics_summary())

    async def get_status(self, request: web.Request) -> web.Response:
        """Get detailed status information."""
        # This would be populated by the daemon
        status = {
            "daemon": {"running": True},
            "endpoints": {},
            "metrics": metrics.get_metrics_summary(),
        }
        return web.json_response(status)

    async def start(self) -> None:
        """Start the health check server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "localhost", self.port)
        await site.start()

    async def stop(self) -> None:
        """Stop the health check server."""
        if hasattr(self, "runner") and self.runner:
            await self.runner.cleanup()
