"""Deterministic local mock of a Perforce changelist API backed by JSON.

Each record needs ``change``, ``user``, ``description`` and ``files`` plus
exactly one way to place it in time:

* ``"timestamp"``: an ISO-8601 datetime **with** a UTC offset, or
* ``"days_ago"`` (integer >= 0) and optional ``"hour"`` (0-23, default 12):
  that many calendar days before the reference time, at that wall-clock hour
  in the reference time's zone. Relative records keep the demo populated on
  any run date; a relative record that lands after the reference time is
  simply outside the requested range (it is never clamped).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .models import Changelist

REQUIRED = ("change", "user", "description", "files")


class MockDataError(ValueError):
    """Invalid mock Perforce data, with file and record context."""


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class MockP4Client:
    def __init__(self, data_path: Path, as_of: datetime):
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        self.data_path = Path(data_path)
        self.as_of = as_of

    def _error(self, index: int | None, message: str) -> MockDataError:
        where = f"{self.data_path}" + ("" if index is None else f" record {index}")
        return MockDataError(f"{where}: {message}")

    def _timestamp(self, index: int, item: dict[str, Any]) -> datetime:
        if ("timestamp" in item) == ("days_ago" in item):
            raise self._error(index, "provide exactly one of 'timestamp' or 'days_ago'")
        if "timestamp" in item:
            if "hour" in item:
                raise self._error(index, "'hour' is only valid with 'days_ago'")
            raw = item["timestamp"]
            try:
                stamp = datetime.fromisoformat(raw) if isinstance(raw, str) else None
            except ValueError:
                stamp = None
            if stamp is None:
                raise self._error(index, f"'timestamp' is not an ISO-8601 datetime: {raw!r}")
            if stamp.utcoffset() is None:
                raise self._error(index, f"'timestamp' must include a UTC offset: {raw!r}")
            return stamp
        days_ago = _int(item["days_ago"])
        if days_ago is None or days_ago < 0:
            raise self._error(index, f"'days_ago' must be an integer >= 0, got {item['days_ago']!r}")
        hour = _int(item.get("hour", 12))
        if hour is None or not 0 <= hour <= 23:
            raise self._error(index, f"'hour' must be an integer 0-23, got {item.get('hour')!r}")
        day = self.as_of.date() - timedelta(days=days_ago)
        return datetime.combine(day, time(hour), tzinfo=self.as_of.tzinfo)

    def load_all(self) -> list[Changelist]:
        try:
            records = json.loads(self.data_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise self._error(None, f"invalid JSON: {exc}") from exc
        if not isinstance(records, list):
            raise self._error(None, "top level must be a JSON array of changelist records")
        result: list[Changelist] = []
        seen: dict[int, int] = {}
        for index, item in enumerate(records):
            if not isinstance(item, dict):
                raise self._error(index, "record must be a JSON object")
            missing = [key for key in REQUIRED if key not in item]
            if missing:
                raise self._error(index, "missing required field(s): " + ", ".join(missing))
            files = item["files"]
            if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
                raise self._error(index, "'files' must be a list of strings")
            try:
                change = Changelist(item["change"], item["user"], self._timestamp(index, item),
                                    item["description"], tuple(files))
            except (TypeError, ValueError) as exc:
                if isinstance(exc, MockDataError):
                    raise
                raise self._error(index, str(exc)) from exc
            if change.change in seen:
                raise self._error(index, f"duplicate changelist number {change.change} "
                                         f"(first seen in record {seen[change.change]})")
            seen[change.change] = index
            result.append(change)
        return result

    def get_changelists(self, start: datetime, end: datetime) -> list[Changelist]:
        lo, hi = start.astimezone(UTC), end.astimezone(UTC)
        return [c for c in self.load_all() if lo <= c.timestamp.astimezone(UTC) < hi]
