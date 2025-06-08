#!/usr/bin/env python
"""Command line interface for server-monitor."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Callable, Mapping, MutableMapping
from logging import Handler
from logging.handlers import RotatingFileHandler
from typing import Any

import click
import structlog
import yaml
from rich.console import Console
from rich.table import Table

from .config import load_config
from .monitor import MonitorDaemon


def setup_logging(
    log_level: str = "INFO",
    log_file: str | None = None,
    log_max_bytes: int = 5 * 1024 * 1024,
    log_backup_count: int = 3,
) -> None:
    """Set up logging configuration."""
    # Create log handlers
    log_handlers: list[Handler] = [logging.StreamHandler()]
    if log_file:
        log_handlers.append(
            RotatingFileHandler(
                log_file, maxBytes=log_max_bytes, backupCount=log_backup_count
            )
        )

    processors: list[
        Callable[
            [Any, str, MutableMapping[str, Any]],
            Mapping[str, Any] | str | bytes | bytearray | tuple[Any, ...],
        ]
    ] = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        structlog.processors.JSONRenderer(),
    ]

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
        handlers=log_handlers,
    )

    # Configure structlog
    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


@click.group()
def cli() -> None:
    """Server Monitor - A flexible monitoring daemon for servers and endpoints."""
    pass


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def start(config_path: str) -> None:
    """Start the monitoring daemon."""
    try:
        # Load configuration
        config = load_config(config_path)

        # Configure logging
        log_level = config.global_config.log_level
        log_file = config.global_config.log_file
        log_max_bytes = config.global_config.log_max_bytes
        log_backup_count = config.global_config.log_backup_count
        setup_logging(log_level, log_file, log_max_bytes, log_backup_count)

        logger = structlog.get_logger("cli")
        logger.info("Starting server-monitor daemon", config_path=config_path)

        # Create and start daemon
        daemon = MonitorDaemon(config)

        # Run event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(daemon.initialize())

        try:
            loop.run_until_complete(daemon.start())
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, shutting down...")
        finally:
            loop.run_until_complete(daemon.stop())
            loop.close()

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
def status(config_path: str, output: str) -> None:
    """Check the status of the monitors (requires running daemon with socket enabled)."""
    try:
        # Load configuration
        config = load_config(config_path)
        console = Console()

        # TODO: Implement reading status from socket/API
        # For now, we'll just show the configuration

        if output == "json":
            click.echo(
                json.dumps(config.dict(by_alias=True, exclude_none=True), indent=2)
            )
        else:
            # Display in a nice table
            table = Table(title="Server Monitor Configuration")
            table.add_column("Endpoint", style="green")
            table.add_column("Type", style="blue")
            table.add_column("Interval", style="cyan")
            table.add_column("Enabled", style="magenta")

            for endpoint in config.endpoints:
                table.add_row(
                    endpoint.name,
                    endpoint.type.value,
                    f"{endpoint.interval}s",
                    "✓" if endpoint.enabled else "✗",
                )

            console.print(table)

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="config.yaml",
    help="Output config file path",
)
def generate_config(output: str) -> None:
    """Generate a sample configuration file."""
    sample_config = {
        "global": {
            "log_level": "INFO",
            "log_file": "server-monitor.log",
            "log_max_bytes": 5242880,
            "log_backup_count": 3,
            "max_concurrent_checks": 10,
            "email_notifications": {
                "enabled": True,
                "events": ["both"],
                "smtp": {
                    "host": "smtp.example.com",
                    "port": 587,
                    "username": "user@example.com",
                    "password": "your-password",
                    "use_tls": True,
                    "from_email": "monitor@example.com",
                },
                "recipients": ["alerts@example.com"],
                "subject_template": "Monitor Alert: {endpoint_name} - {status}",
            },
            "webhook_notifications": {
                "enabled": True,
                "events": ["failure"],
                "webhook": {
                    "url": "https://hooks.slack.com/services/your/webhook/url",
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "timeout": 30,
                },
            },
            "database": {"type": "sqlite", "database": "monitor.db"},
        },
        "endpoints": [
            {
                "name": "Example Website",
                "type": "http",
                "interval": 60,
                "enabled": True,
                "http": {
                    "url": "https://example.com",
                    "method": "GET",
                    "timeout": 30,
                    "expected_status": 200,
                    "content_match": "Example Domain",
                    "follow_redirects": True,
                },
            },
            {
                "name": "Example API",
                "type": "http",
                "interval": 30,
                "enabled": True,
                "http": {
                    "url": "https://api.example.com/health",
                    "method": "GET",
                    "headers": {"Authorization": "Bearer your-token"},
                    "timeout": 5,
                    "expected_status": 200,
                },
            },
            {
                "name": "Database Server",
                "type": "tcp",
                "interval": 120,
                "enabled": True,
                "tcp": {"host": "db.example.com", "port": 5432, "timeout": 10},
            },
            {
                "name": "HTTPS Certificate",
                "type": "tls",
                "interval": 86400,
                "enabled": True,
                "tls": {
                    "host": "example.com",
                    "port": 443,
                    "timeout": 30,
                    "cert_expiry_warning_days": 30,
                },
                "email_notifications": {"events": ["failure"]},
            },
        ],
    }

    # Write configuration to file
    with open(output, "w") as f:
        yaml.dump(sample_config, f, default_flow_style=False, sort_keys=False)

    click.echo(f"Sample configuration written to {output}")


@cli.command()
def health() -> None:
    """Health check endpoint for Docker container monitoring."""
    try:
        click.echo("OK")
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(1)


def main() -> None:
    """Entry point for the application."""
    cli()


if __name__ == "__main__":
    main()
