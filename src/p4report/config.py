"""Application configuration and paths."""
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEZONE = "America/Los_Angeles"


@dataclass(frozen=True)
class AppConfig:
    userlist: Path = ROOT / "data" / "userlist.txt"
    mock_data: Path = ROOT / "data" / "mock_p4_data.json"
    reports_dir: Path = ROOT / "reports"
    timezone: str = DEFAULT_TIMEZONE

    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown reporting timezone: {self.timezone}") from exc
