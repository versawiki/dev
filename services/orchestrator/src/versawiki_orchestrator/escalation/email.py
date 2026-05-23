"""Email escalation via SMTP.

Used for two things:
1. Agent flagged its run as `[needs-review]` (uncertain ticket, conflict,
   anomaly the agent thinks a human should see)
2. Spending cap tripped — the orchestrator paused itself

The implementation is intentionally bare-bones: aiosmtplib + STARTTLS,
plain text body, single recipient. Works against any SMTP provider with
app-password / API-key style auth (Resend, Postmark, Gmail SMTP).
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Iterable

import aiosmtplib
import structlog

from ..config import Settings


_log = structlog.get_logger("versawiki_orchestrator.escalation")


class EscalationError(Exception):
    """Wraps any SMTP / config failure when sending an escalation."""


class EmailEscalator:
    """Send a single email to the configured recipient.

    `send(subject, body)` is fire-and-forget; failures are logged and an
    `EscalationError` is raised so the caller can record the failure in
    the audit log instead of trying again immediately.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def is_configured(self) -> bool:
        s = self._settings
        return bool(s.smtp_host and s.smtp_username and s.smtp_password.get_secret_value())

    async def send(
        self,
        *,
        subject: str,
        body: str,
        extra_to: Iterable[str] | None = None,
    ) -> None:
        s = self._settings
        if not self.is_configured:
            raise EscalationError("SMTP not configured (smtp_host / username / password)")

        msg = EmailMessage()
        msg["From"] = s.escalation_from
        recipients = [s.escalation_to, *(extra_to or [])]
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            await aiosmtplib.send(
                msg,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_username,
                password=s.smtp_password.get_secret_value(),
                start_tls=s.smtp_use_starttls,
            )
            _log.info("escalation_sent", subject=subject, to=recipients)
        except Exception as exc:  # noqa: BLE001 — wrap-and-rethrow
            _log.warning("escalation_failed", error=str(exc))
            raise EscalationError(f"escalation send failed: {exc}") from exc
