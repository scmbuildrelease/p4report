"""Load and validate the pipe-separated employee directory.

Format: ``name|email|p4_username`` per line; blank lines and ``#`` comments
are ignored; a UTF-8 byte-order mark is accepted. Perforce usernames and
email addresses must be unique (case-insensitively). Duplicate display names
are allowed because two people can share a name; they are told apart by
email and username, and ties in the report are broken by username.
"""
from __future__ import annotations

from pathlib import Path

from .models import Employee, is_valid_email


class UserListError(ValueError):
    """Invalid employee directory, with file and line context."""


def load_users(path: Path) -> list[Employee]:
    path = Path(path)
    employees: list[Employee] = []
    usernames: dict[str, int] = {}
    emails: dict[str, int] = {}

    def fail(line_no: int, message: str) -> UserListError:
        return UserListError(f"{path} line {line_no}: {message}")

    for line_no, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        row = raw.strip()
        if not row or row.startswith("#"):
            continue
        fields = [part.strip() for part in row.split("|")]
        if len(fields) != 3:
            raise fail(line_no, f"expected 3 fields name|email|p4_username, found {len(fields)}")
        name, email, username = fields
        for label, value in (("name", name), ("email", email), ("p4_username", username)):
            if not value:
                raise fail(line_no, f"{label} must not be empty")
        if not is_valid_email(email):
            raise fail(line_no, f"invalid email address {email!r}")
        if any(ch.isspace() for ch in username):
            raise fail(line_no, f"Perforce username must not contain whitespace: {username!r}")
        user_key, email_key = username.casefold(), email.casefold()
        if user_key in usernames:
            raise fail(line_no, f"duplicate Perforce username {username!r} (first on line {usernames[user_key]})")
        if email_key in emails:
            raise fail(line_no, f"duplicate email address {email!r} (first on line {emails[email_key]})")
        usernames[user_key], emails[email_key] = line_no, line_no
        employees.append(Employee(name, email, username))
    if not employees:
        raise UserListError(f"{path}: no employee records found")
    return employees
