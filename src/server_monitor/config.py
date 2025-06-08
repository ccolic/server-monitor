"""Configuration models for the server monitor."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class CheckType(str, Enum):
    """Available check types."""

    HTTP = "http"
    TCP = "tcp"
    TLS = "tls"


class NotificationEvent(str, Enum):
    """When to send notifications."""

    FAILURE = "failure"
    RECOVERY = "recovery"
    BOTH = "both"


class DatabaseType(str, Enum):
    """Supported database types."""

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"


class SMTPConnectionMethod(str, Enum):
    """SMTP connection methods."""

    STARTTLS = "starttls"
    SSL = "ssl"
    PLAIN = "plain"


class SMTPConfig(BaseModel):
    """SMTP configuration."""

    host: str
    port: int = 587
    username: str | None = None
    password: str | None = None
    connection_method: SMTPConnectionMethod = SMTPConnectionMethod.STARTTLS
    from_email: str


class WebhookConfig(BaseModel):
    """Webhook configuration."""

    url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: int = 30


class NotificationConfig(BaseModel):
    """Base notification configuration."""

    enabled: bool = True
    events: list[NotificationEvent] = Field(
        default_factory=lambda: [NotificationEvent.BOTH]
    )


class EmailNotificationConfig(NotificationConfig):
    """Email notification configuration."""

    smtp: SMTPConfig | None = None
    recipients: list[str] | None = None
    subject_template: str = "Monitor Alert: {endpoint_name} - {status}"

    @model_validator(mode="after")
    def validate_enabled_fields(self) -> EmailNotificationConfig:
        """Validate that required fields are present when enabled."""
        if self.enabled:
            if self.smtp is None:
                raise ValueError(
                    "smtp configuration is required when email notifications are enabled"
                )
            if self.recipients is None or not self.recipients:
                raise ValueError(
                    "recipients list is required when email notifications are enabled"
                )
        return self


class WebhookNotificationConfig(NotificationConfig):
    """Webhook notification configuration."""

    webhook: WebhookConfig | None = None

    @model_validator(mode="after")
    def validate_enabled_fields(self) -> WebhookNotificationConfig:
        """Validate that required fields are present when enabled."""
        if self.enabled:
            if self.webhook is None:
                raise ValueError(
                    "webhook configuration is required when webhook notifications are enabled"
                )
        return self


class DatabaseConfig(BaseModel):
    """Database configuration."""

    type: DatabaseType
    url: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None

    @model_validator(mode="after")
    def validate_database_config(self) -> DatabaseConfig:
        """Validate database configuration."""
        if self.url:
            return self

        if self.type == DatabaseType.SQLITE:
            database = self.database or "monitor.db"
            self.url = f"sqlite:///{database}"
        elif self.type == DatabaseType.POSTGRESQL:
            host = self.host or "localhost"
            port = self.port or 5432
            database = self.database or "monitor"
            username = self.username or "postgres"
            password = self.password or ""
            self.url = f"postgresql://{username}:{password}@{host}:{port}/{database}"
        else:
            raise ValueError(f"Unsupported database type: {self.type}")

        return self


class HTTPCheckConfig(BaseModel):
    """HTTP check configuration."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: int = 30
    expected_status: int | list[int] = 200
    content_match: str | None = None
    content_regex: bool = False
    follow_redirects: bool = True
    verify_ssl: bool = True

    @model_validator(mode="after")
    def validate_http_check_config(self) -> HTTPCheckConfig:
        """Validate HTTP check configuration."""
        if not self.url or not isinstance(self.url, str) or self.url.strip() == "":
            raise ValueError("HTTPCheckConfig: url must be a non-empty string")
        if self.method not in (
            "GET",
            "POST",
            "PUT",
            "DELETE",
            "HEAD",
            "OPTIONS",
            "PATCH",
        ):
            raise ValueError(f"HTTPCheckConfig: method '{self.method}' is not valid")
        return self


class TCPCheckConfig(BaseModel):
    """TCP check configuration."""

    host: str
    port: int
    timeout: int = 10

    @model_validator(mode="after")
    def validate_tcp_check_config(self) -> TCPCheckConfig:
        """Validate TCP check configuration."""
        if not (0 < self.port < 65536):
            raise ValueError("TCPCheckConfig: port must be between 1 and 65535")
        return self


class TLSCheckConfig(BaseModel):
    """TLS check configuration."""

    host: str
    port: int = 443
    timeout: int = 10
    cert_expiry_warning_days: int = 30

    @model_validator(mode="after")
    def validate_tls_check_config(self) -> TLSCheckConfig:
        """Validate TLS check configuration."""
        if (
            self.cert_expiry_warning_days is not None
            and self.cert_expiry_warning_days < 0
        ):
            raise ValueError("TLSCheckConfig: cert_expiry_warning_days must be >= 0")
        return self


class EndpointConfig(BaseModel):
    """Endpoint configuration."""

    name: str
    type: CheckType
    interval: int = 60  # seconds
    enabled: bool = True

    # Check-specific configuration
    http: HTTPCheckConfig | None = None
    tcp: TCPCheckConfig | None = None
    tls: TLSCheckConfig | None = None

    # Notification overrides
    email_notifications: EmailNotificationConfig | None = None
    webhook_notifications: WebhookNotificationConfig | None = None

    @model_validator(mode="after")
    def validate_check_config(self) -> EndpointConfig:
        """Validate check-specific configuration."""
        if self.type == CheckType.HTTP and self.http is None:
            raise ValueError("HTTP configuration required for HTTP checks")

        if self.type == CheckType.TCP and self.tcp is None:
            raise ValueError("TCP configuration required for TCP checks")

        if self.type == CheckType.TLS and self.tls is None:
            raise ValueError("TLS configuration required for TLS checks")

        return self


class GlobalConfig(BaseModel):
    """Global configuration."""

    log_level: str = "INFO"
    log_file: str | None = None
    log_max_bytes: int = 5242880  # Default: 5 MB
    log_backup_count: int = 3  # Default: 3 backups
    max_concurrent_checks: int = 10

    # Default notification settings
    email_notifications: EmailNotificationConfig | None = None
    webhook_notifications: WebhookNotificationConfig | None = None

    # Database configuration
    database: DatabaseConfig


class MonitorConfig(BaseModel):
    """Main configuration model."""

    global_config: GlobalConfig = Field(alias="global")
    endpoints: list[EndpointConfig]

    # The following 'type: ignore' is required for mypy compatibility with Python 3.8,
    # where TypedDict does not allow extra keys. It is safe to ignore the 'unused-ignore'
    # warning in Python 3.11+.
    model_config = {
        "validate_by_name": True,  # type: ignore
    }

    @classmethod
    def from_yaml(cls, file_path: str | Path) -> MonitorConfig:
        """Load configuration from YAML file."""
        with open(file_path) as f:
            data = yaml.safe_load(f)

        # Load sensitive information from environment variables
        if (
            "email_notifications" in data["global"]
            and "smtp" in data["global"]["email_notifications"]
        ):
            data["global"]["email_notifications"]["smtp"]["password"] = os.getenv(
                "SMTP_PASSWORD",
                data["global"]["email_notifications"]["smtp"].get("password"),
            )

        # Validate configuration structure
        cls.validate_config_structure(data)

        return cls(**data)

    @staticmethod
    def validate_config_structure(data: dict[str, Any]) -> None:
        """Validate the structure and values of the configuration."""
        if "global" not in data:
            raise ValueError("Missing 'global' section in configuration.")

        if "endpoints" not in data or not isinstance(data["endpoints"], list):
            raise ValueError("'endpoints' section must be a list.")

        for endpoint in data["endpoints"]:
            if "name" not in endpoint or not endpoint["name"]:
                raise ValueError("Each endpoint must have a 'name'.")
            if "type" not in endpoint or endpoint["type"] not in ["http", "tcp", "tls"]:
                raise ValueError(
                    "Invalid 'type' for endpoint: must be 'http', 'tcp', or 'tls'."
                )

    def to_yaml(self, file_path: str | Path) -> None:
        """Save configuration to YAML file."""
        data = self.model_dump(by_alias=True, exclude_none=True)
        with open(file_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, indent=2)


def load_config(config_path: str | Path) -> MonitorConfig:
    """Load configuration from file."""
    return MonitorConfig.from_yaml(config_path)
