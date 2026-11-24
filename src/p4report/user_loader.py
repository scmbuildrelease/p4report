"""Load and validate pipe-separated employee records."""
from pathlib import Path
from .models import Employee


class UserListError(ValueError):
    """Invalid employee directory, with line context."""


def load_users(path: Path) -> list[Employee]:
    employees: list[Employee] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = raw.strip()
        if not row or row.startswith("#"):
            continue
        fields = [part.strip() for part in row.split("|")]
        if len(fields) != 3 or any(not field for field in fields):
            raise UserListError(f"Line {line_no}: expected non-empty name|email|p4_username")
        name, email, username = fields
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise UserListError(f"Line {line_no}: invalid email address")
        if username in seen:
            raise UserListError(f"Line {line_no}: duplicate Perforce username {username!r}")
        seen.add(username)
        employees.append(Employee(name, email, username))
    return employees
