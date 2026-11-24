"""Deterministic local mock of a Perforce changelist API."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from .models import Changelist


class MockP4Client:
    def __init__(self, data_path: Path):
        self.data_path = data_path

    def get_changelists(self, as_of: datetime) -> list[Changelist]:
        records = json.loads(self.data_path.read_text(encoding="utf-8"))
        result = []
        for item in records:
            days_ago = int(item["days_ago"])
            hour = int(item.get("hour", 12))
            if days_ago == 0:
                hour = min(hour, as_of.hour)
            stamp = (as_of - timedelta(days=int(item["days_ago"]))).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            result.append(Changelist(int(item["change"]), item["user"], stamp,
                                     item["description"], tuple(item["files"])))
        return result
