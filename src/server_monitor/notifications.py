"""Notification system for monitoring alerts."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiosmtplib
import httpx
import structlog

from .config import (
    EmailNotificationConfig,
    NotificationEvent,
    SMTPConnectionMethod,
    WebhookNotificationConfig,
)
from .database import CheckResult, CheckStatus

logger = structlog.get_logger(__name__)


class NotificationContext:
    """Context information for notifications."""

    def __init__(
        self,
        result: CheckResult,
        previous_status: CheckStatus | None = None,
        failure_count: int = 0,
    ):
        self.result = result
        self.previous_status = previous_status
        self.failure_count = failure_count
        self.is_state_change = (
            previous_status != result.status if previous_status else True
        )
        self.is_recovery = (
            previous_status in [CheckStatus.FAILURE, CheckStatus.ERROR]
            and result.status == CheckStatus.SUCCESS
        )
        self.is_failure = result.status in [CheckStatus.FAILURE, CheckStatus.ERROR]


class BaseNotifier(ABC):
    """Base class for notification implementations."""

    def __init__(self, config: Any):
        self.config = config

    @abstractmethod
    async def send_notification(self, context: NotificationContext) -> bool:
        """Send notification. Returns True if successful."""
        pass

    def should_notify(self, context: NotificationContext) -> bool:
        """Determine if notification should be sent based on events configuration."""
        if not self.config.enabled:
            return False

        events = self.config.events

        # Check if we should notify based on configured events
        if NotificationEvent.BOTH in events:
            return True
        elif NotificationEvent.FAILURE in events and context.is_failure:
            return True
        elif NotificationEvent.RECOVERY in events and context.is_recovery:
            return True

        return False


class EmailNotifier(BaseNotifier):
    """Email notification implementation."""

    def __init__(self, config: EmailNotificationConfig):
        super().__init__(config)
        if config.smtp is None:
            raise ValueError("SMTP configuration is required for email notifications")
        self.smtp_config = config.smtp

    async def send_notification(self, context: NotificationContext) -> bool:
        """Send email notification."""
        try:
            # Create email message
            msg = MIMEMultipart()
            msg["From"] = self.smtp_config.from_email
            if self.config.recipients is None:
                raise ValueError("Recipients list is required for email notifications")
            msg["To"] = ", ".join(self.config.recipients)

            # Format subject
            status_text = (
                "RECOVERED"
                if context.is_recovery
                else context.result.status.value.upper()
            )
            subject = self.config.subject_template.format(
                endpoint_name=context.result.endpoint_name, status=status_text
            )
            msg["Subject"] = subject

            # Create email body
            body = self._create_email_body(context)
            msg.attach(MIMEText(body, "html"))

            # Send email
            async with aiosmtplib.SMTP(
                hostname=self.smtp_config.host,
                port=self.smtp_config.port,
                use_tls=(
                    self.smtp_config.connection_method == SMTPConnectionMethod.SSL
                ),
                start_tls=(
                    self.smtp_config.connection_method == SMTPConnectionMethod.STARTTLS
                ),
            ) as smtp:
                if self.smtp_config.username and self.smtp_config.password:
                    await smtp.login(
                        self.smtp_config.username, self.smtp_config.password
                    )
                await smtp.send_message(msg)

            logger.info(
                "Email notification sent",
                endpoint=context.result.endpoint_name,
                status=context.result.status,
                recipients=self.config.recipients,
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to send email notification",
                endpoint=context.result.endpoint_name,
                error=str(e),
            )
            return False

    def _create_email_body(self, context: NotificationContext) -> str:
        """Create HTML email body."""
        result = context.result

        # Determine status color
        if result.status == CheckStatus.SUCCESS:
            status_color = "#28a745"  # Green
        elif result.status == CheckStatus.FAILURE:
            status_color = "#dc3545"  # Red
        else:
            status_color = "#ffc107"  # Yellow

        # Create details table
        details_rows = ""
        if result.details:
            for key, value in result.details.items():
                details_rows += (
                    f"<tr><td><strong>{key}:</strong></td><td>{value}</td></tr>"
                )

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: {status_color}; color: white; padding: 15px; border-radius: 5px; }}
                .content {{ padding: 20px; border: 1px solid #ddd; border-radius: 5px; margin-top: 10px; }}
                .status {{ font-size: 24px; font-weight: bold; }}
                .details {{ margin-top: 20px; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
                .timestamp {{ color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="status">{result.status.value.upper()}</div>
                <div>Endpoint: {result.endpoint_name}</div>
            </div>

            <div class="content">
                <h3>Check Details</h3>
                <table>
                    <tr><td><strong>Check Type:</strong></td><td>{result.check_type}</td></tr>
                    <tr><td><strong>Status:</strong></td><td>{result.status.value}</td></tr>
                    <tr><td><strong>Timestamp:</strong></td><td>{result.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}</td></tr>
                    {f"<tr><td><strong>Response Time:</strong></td><td>{result.response_time:.3f}s</td></tr>" if result.response_time else ""}
                    {f"<tr><td><strong>Error:</strong></td><td>{result.error_message}</td></tr>" if result.error_message else ""}
                    {f"<tr><td><strong>Failure Count:</strong></td><td>{context.failure_count}</td></tr>" if context.failure_count > 0 else ""}
                </table>

                {f'<div class="details"><h4>Additional Details</h4><table>{details_rows}</table></div>' if details_rows else ""}
            </div>
        </body>
        </html>
        """

        return html_body


class WebhookNotifier(BaseNotifier):
    """Webhook notification implementation."""

    def __init__(self, config: WebhookNotificationConfig):
        super().__init__(config)
        if config.webhook is None:
            raise ValueError(
                "Webhook configuration is required for webhook notifications"
            )
        self.webhook_config = config.webhook

    async def send_notification(self, context: NotificationContext) -> bool:
        """Send webhook notification."""
        try:
            # Create webhook payload
            payload = self._create_webhook_payload(context)

            # Send webhook
            async with httpx.AsyncClient(timeout=self.webhook_config.timeout) as client:
                response = await client.request(
                    method=self.webhook_config.method,
                    url=self.webhook_config.url,
                    headers=self.webhook_config.headers,
                    json=payload,
                )

                response.raise_for_status()

            logger.info(
                "Webhook notification sent",
                endpoint=context.result.endpoint_name,
                status=context.result.status,
                webhook_url=self.webhook_config.url,
                response_status=response.status_code,
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to send webhook notification",
                endpoint=context.result.endpoint_name,
                webhook_url=self.webhook_config.url,
                error=str(e),
            )
            return False

    def _create_webhook_payload(self, context: NotificationContext) -> dict[str, Any]:
        """Create webhook payload."""
        result = context.result

        payload = {
            "timestamp": result.timestamp.isoformat(),
            "endpoint_name": result.endpoint_name,
            "check_type": result.check_type,
            "status": result.status.value,
            "is_recovery": context.is_recovery,
            "is_failure": context.is_failure,
            "failure_count": context.failure_count,
        }

        if result.response_time is not None:
            payload["response_time"] = str(result.response_time)

        if result.error_message:
            payload["error_message"] = str(result.error_message)

        if result.details:
            payload["details"] = json.dumps(result.details)

        return payload


class NotificationManager:
    """Manages all notification sending."""

    def __init__(self) -> None:
        self.notifiers: list[BaseNotifier] = []

    def add_notifier(self, notifier: BaseNotifier) -> None:
        """Add a notifier to the manager."""
        self.notifiers.append(notifier)

    async def send_notifications(self, context: NotificationContext) -> None:
        """Send notifications through all configured notifiers."""
        if not self.notifiers:
            return

        # Filter notifiers that should send notifications
        active_notifiers = [
            notifier for notifier in self.notifiers if notifier.should_notify(context)
        ]

        if not active_notifiers:
            logger.debug(
                "No notifications to send",
                endpoint=context.result.endpoint_name,
                status=context.result.status,
            )
            return

        # Send notifications concurrently
        tasks = [notifier.send_notification(context) for notifier in active_notifiers]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log results
        successful = sum(1 for result in results if result is True)
        failed = len(results) - successful

        logger.info(
            "Notifications sent",
            endpoint=context.result.endpoint_name,
            status=context.result.status,
            successful=successful,
            failed=failed,
            total=len(active_notifiers),
        )


def create_notification_manager(
    global_email_config: EmailNotificationConfig | None = None,
    global_webhook_config: WebhookNotificationConfig | None = None,
    endpoint_email_config: EmailNotificationConfig | None = None,
    endpoint_webhook_config: WebhookNotificationConfig | None = None,
) -> NotificationManager:
    """Create notification manager with configured notifiers."""
    manager = NotificationManager()

    # Use endpoint-specific config if available, otherwise use global config
    email_config = endpoint_email_config or global_email_config
    webhook_config = endpoint_webhook_config or global_webhook_config

    if email_config and email_config.enabled:
        manager.add_notifier(EmailNotifier(email_config))

    if webhook_config and webhook_config.enabled:
        manager.add_notifier(WebhookNotifier(webhook_config))

    return manager
