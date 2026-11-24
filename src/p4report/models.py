"""Validated data models for employee and changelist records."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# Pragmatic address check: one "@", dot-atom local part, and a dotted domain of
# DNS labels. It rejects whitespace, "@@", empty parts and consecutive dots.
_LOCAL = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
EMAIL_RE = re.compile(rf"^{_LOCAL}@{_LABEL}(?:\.{_LABEL})+$")


def is_valid_email(value: str) -> bool:
    return len(value) <= 254 and EMAIL_RE.fullmatch(value) is not None


def normalize_username(username: str) -> str:
    """Perforce usernames are matched case-insensitively (see README)."""
    return username.strip().casefold()


@dataclass(frozen=True)
class Employee:
    name: str
    email: str
    username: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("employee name must not be empty")
        if not is_valid_email(self.email):
            raise ValueError(f"invalid email address {self.email!r}")
        if not self.username.strip() or any(ch.isspace() for ch in self.username):
            raise ValueError(f"invalid Perforce username {self.username!r}")

    @property
    def key(self) -> str:
        return normalize_username(self.username)


@dataclass(frozen=True)
class Changelist:
    change: int
    user: str
    timestamp: datetime
    description: str
    files: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.change, bool) or not isinstance(self.change, int) or self.change <= 0:
            raise ValueError(f"changelist number must be a positive integer, got {self.change!r}")
        if not isinstance(self.user, str) or not self.user.strip():
            raise ValueError(f"changelist {self.change}: Perforce username must not be empty")
        if not isinstance(self.timestamp, datetime):
            raise TypeError(f"changelist {self.change}: timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            # A naive value would silently be read in the host's local zone.
            raise ValueError(f"changelist {self.change}: timestamp must be timezone-aware")
        if not isinstance(self.description, str):
            raise TypeError(f"changelist {self.change}: description must be a string")
        if not isinstance(self.files, tuple) or not all(isinstance(f, str) for f in self.files):
            raise TypeError(f"changelist {self.change}: files must be a tuple of strings")
