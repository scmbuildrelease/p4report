from datetime import UTC, datetime

import pytest

from p4report.models import Changelist, Employee, is_valid_email

STAMP = datetime(2025, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(("args", "needle"), [
    ((" ", "a@example.com", "a"), "name must not be empty"),
    (("A", "nope", "a"), "invalid email"),
    (("A", "a@example.com", "a b"), "invalid Perforce username"),
    (("A", "a@example.com", ""), "invalid Perforce username"),
])
def test_employee_validation(args, needle):
    with pytest.raises(ValueError, match=needle):
        Employee(*args)


@pytest.mark.parametrize(("args", "error", "needle"), [
    ((1, "a", "2025-01-01", "d", ()), TypeError, "timestamp must be a datetime"),
    ((1, "a", STAMP, "d", ["//f"]), TypeError, "files must be a tuple"),
    ((1, "a", STAMP, "d", (1,)), TypeError, "files must be a tuple"),
    ((1, "a", STAMP, None, ()), TypeError, "description must be a string"),
    ((1, None, STAMP, "d", ()), ValueError, "username must not be empty"),
    ((1, "a", datetime(2025, 1, 1), "d", ()), ValueError, "timezone-aware"),
])
def test_changelist_validation(args, error, needle):
    with pytest.raises(error, match=needle):
        Changelist(*args)


@pytest.mark.parametrize(("value", "ok"), [
    ("first.last+tag@sub.example.co.uk", True), ("a@b.io", True),
    ("a@b", False), ("a@-b.com", False), (".a@b.com", False), ("a@b..com", False), ("a" * 250 + "@b.com", False),
])
def test_email_syntax(value, ok):
    assert is_valid_email(value) is ok
