"""Outgoing e-mail (A4): one small interface, three backends chosen by
`STUDIO_EMAIL_BACKEND`, SMTP credentials read from the environment only.

Messages carry account secrets (verification and reset links): they are never
logged. Delivery failures are logged with the recipient digest and the
exception class only, never the message body.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from studio_api.security_log import email_digest
from studio_api.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str
    kind: str


class EmailSender(Protocol):
    enabled: bool

    async def send(self, message: OutgoingEmail) -> None: ...


class DisabledEmailSender:
    enabled = False

    async def send(self, message: OutgoingEmail) -> None:
        return None


def _build(message: OutgoingEmail, sender: str) -> EmailMessage:
    mime = EmailMessage()
    mime["From"] = sender
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime.set_content(message.body)
    return mime


class FileEmailSender:
    """Local development: each message becomes an .eml file (no SMTP server,
    no secret in the logs)."""

    enabled = True

    def __init__(self, directory: str, sender: str) -> None:
        self._directory = Path(directory)
        self._sender = sender

    async def send(self, message: OutgoingEmail) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = self._directory / f"{stamp}-{message.kind}-{uuid.uuid4().hex[:8]}.eml"
        path.write_bytes(bytes(_build(message, self._sender)))


class SmtpEmailSender:
    enabled = True

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _send_blocking(self, mime: EmailMessage) -> None:
        s = self._settings
        assert s.smtp_host is not None
        context = ssl.create_default_context()
        smtp: smtplib.SMTP
        if s.smtp_security == "tls":
            smtp = smtplib.SMTP_SSL(
                s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context
            )
        else:
            smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds)
        with smtp:
            if s.smtp_security == "starttls":
                smtp.starttls(context=context)
            if s.smtp_username and s.smtp_password:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(mime)

    async def send(self, message: OutgoingEmail) -> None:
        assert self._settings.email_from is not None
        await asyncio.to_thread(self._send_blocking, _build(message, self._settings.email_from))


def email_settings_problems(settings: Settings) -> list[str]:
    """Configuration errors that refuse startup (never mentions a secret value)."""
    problems: list[str] = []
    if settings.email_backend != "disabled" and not settings.email_from:
        problems.append("STUDIO_EMAIL_FROM is required when an e-mail backend is enabled")
    if settings.email_backend == "smtp" and not settings.smtp_host:
        problems.append("STUDIO_SMTP_HOST is required with STUDIO_EMAIL_BACKEND=smtp")
    if settings.email_backend == "smtp" and bool(settings.smtp_username) != bool(
        settings.smtp_password
    ):
        problems.append("STUDIO_SMTP_USERNAME and STUDIO_SMTP_PASSWORD go together")
    if settings.public_registration_enabled and settings.email_backend == "disabled":
        problems.append("STUDIO_PUBLIC_REGISTRATION_ENABLED requires an e-mail backend")
    if settings.environment == "production":
        if settings.email_backend == "file":
            problems.append("STUDIO_EMAIL_BACKEND=file is for local development only")
        if settings.public_registration_enabled and not settings.public_base_url.startswith(
            "https://"
        ):
            problems.append("STUDIO_PUBLIC_BASE_URL must be https:// when registration is open")
    return problems


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "smtp":
        return SmtpEmailSender(settings)
    if settings.email_backend == "file":
        assert settings.email_from is not None
        return FileEmailSender(settings.email_file_dir, settings.email_from)
    return DisabledEmailSender()


def get_email_sender() -> EmailSender:
    """FastAPI dependency; tests override it with an in-memory outbox."""
    return build_email_sender(get_settings())


async def deliver(sender: EmailSender, message: OutgoingEmail) -> None:
    """Background delivery: a failure is logged, never raised to the client
    (responses must not depend on whether an e-mail went out)."""
    try:
        await sender.send(message)
    except Exception as exc:
        logger.warning(
            "account e-mail delivery failed: kind=%s to=%s error=%s",
            message.kind,
            email_digest(message.to),
            type(exc).__name__,
        )
