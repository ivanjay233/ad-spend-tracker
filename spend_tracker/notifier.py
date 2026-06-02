"""Alert notification dispatcher — sends alerts via Telegram."""

from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from spend_tracker.models import Alert

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"
DEFAULT_TIMEOUT = 15.0


class AlertNotifier:
    """Dispatches alerts to configured notification channels.

    Currently supports Telegram. Extensible to Slack, email, etc.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._sent_count: int = 0

    @property
    def _client_instance(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def configure(self, bot_token: str, chat_id: str) -> None:
        """Configure or update Telegram credentials."""
        self.bot_token = bot_token
        self.chat_id = chat_id

    async def send_alert(self, alert: Alert) -> bool:
        """Send a single alert via the configured channel.

        Args:
            alert: The alert to send.

        Returns:
            True if sent successfully.
        """
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram not configured — alert not sent: %s", alert.message[:50])
            return False

        message = self._format_alert(alert)
        return await self._send_telegram(message)

    async def send_alerts(self, alerts: List[Alert]) -> int:
        """Send multiple alerts, returning the count of successfully sent.

        Args:
            alerts: List of alerts to dispatch.

        Returns:
            Number of alerts sent successfully.
        """
        sent = 0
        for alert in alerts:
            if await self.send_alert(alert):
                sent += 1
        return sent

    async def send_message(self, text: str) -> bool:
        """Send a plain text message via Telegram.

        Args:
            text: The message text.

        Returns:
            True if sent successfully.
        """
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram not configured — message not sent")
            return False
        return await self._send_telegram(text)

    def _format_alert(self, alert: Alert) -> str:
        """Format an alert as a Telegram-friendly message string."""
        severity_emoji = {
            "critical": "🚨",
            "warning": "⚠️",
            "info": "ℹ️",
        }
        emoji = severity_emoji.get(alert.severity.value, "📢")

        lines = [
            f"{emoji} *Ad Spend Alert*",
            f"*Campaign:* {alert.campaign_name or alert.campaign_id}",
            f"*Type:* {alert.alert_type.value}",
            f"*Severity:* {alert.severity.value.upper()}",
            f"*Spend:* ${alert.current_spend:.2f}",
            "",
            alert.message,
        ]

        if alert.threshold_value is not None:
            lines.append(f"*Threshold:* ${alert.threshold_value:.2f}" if alert.current_spend > 0 else f"*Threshold:* {alert.threshold_value}")

        lines.append(f"🕐 `{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}`")

        return "\n".join(lines)

    async def _send_telegram(self, text: str) -> bool:
        """Send a message via the Telegram Bot API."""
        if not self.bot_token or not self.chat_id:
            return False

        url = f"{TELEGRAM_API_BASE}{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            response = await self._client_instance.post(url, json=payload)
            response.raise_for_status()
            self._sent_count += 1
            logger.debug("Telegram alert sent: %s", text[:60])
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("Telegram API error: %s — %s", exc, response.text)  # type: ignore[possibly-undefined]
            return False
        except httpx.RequestError as exc:
            logger.error("Telegram connection error: %s", exc)
            return False

    @property
    def sent_count(self) -> int:
        """Number of alerts sent since this notifier was created."""
        return self._sent_count

    @property
    def is_configured(self) -> bool:
        """Check if the notifier has Telegram credentials configured."""
        return bool(self.bot_token and self.chat_id)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
