from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import pytest

from p4report.models import Changelist, Employee

LA = ZoneInfo("America/Los_Angeles")
UTC_ZONE = UTC


def emp(name: str, username: str, email: str | None = None) -> Employee:
    return Employee(name, email or f"{username}@example.com", username)


def cl(change: int, user: str, stamp: datetime, description: str = "d", files: tuple[str, ...] = ()) -> Changelist:
    return Changelist(change, user, stamp, description, files)


class FakeSMTP:
    """Records SMTP interactions; never opens a socket."""

    instances: ClassVar[list[FakeSMTP]] = []
    fail_on: ClassVar[str | None] = None
    refused: ClassVar[dict[str, Any]] = {}

    def __init__(self, host: str, port: int, timeout: float = 0, context: Any = None) -> None:
        self.host, self.port, self.timeout, self.ssl_context = host, port, timeout, context
        self.calls: list[tuple[str, Any]] = [("connect", (host, port))]
        self.sent: list[Any] = []
        self.closed = False
        type(self).instances.append(self)
        if self.fail_on == "connect":
            raise ConnectionRefusedError(61, "Connection refused")

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True

    def starttls(self, *, context: Any = None) -> None:
        self.calls.append(("starttls", context))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user))
        if self.fail_on == "login":
            import smtplib
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 authentication failed")

    def send_message(self, msg: Any) -> dict[str, Any]:
        self.calls.append(("send", msg["To"]))
        if self.fail_on == "send":
            import smtplib
            raise smtplib.SMTPDataError(554, b"rejected")
        self.sent.append(msg)
        return self.refused


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> Callable[..., type[FakeSMTP]]:
    from p4report import email_sender

    def install(fail_on: str | None = None, refused: dict[str, Any] | None = None) -> type[FakeSMTP]:
        cls = type("FakeSMTPInstance", (FakeSMTP,), {"instances": [], "fail_on": fail_on,
                                                      "refused": refused or {}})
        monkeypatch.setattr(email_sender.smtplib, "SMTP", cls)
        monkeypatch.setattr(email_sender.smtplib, "SMTP_SSL", cls)
        return cls

    return install


SMTP_ENV = {"SEND_EMAIL": "true", "SMTP_HOST": "smtp.mail.test-provider.net", "SMTP_PORT": "587",
            "SMTP_USERNAME": "report-bot", "SMTP_PASSWORD": "s3cret-pw", "SMTP_FROM": "reports@corp-demo.net",
            "REPORT_RECIPIENT": "manager@corp-demo.net"}
