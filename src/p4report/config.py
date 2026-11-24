"""Application configuration and default paths.

The synthetic demo inputs ship inside the package (``p4report/data``), so the
defaults work for editable and regular installs from any working directory.
User-supplied paths and the output directory are resolved against the current
working directory.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PACKAGE_DATA = Path(__file__).resolve().parent / "data"
DEFAULT_USERLIST = PACKAGE_DATA / "userlist.txt"
DEFAULT_MOCK_DATA = PACKAGE_DATA / "mock_p4_data.json"
DEFAULT_REPORTS_DIR = Path("reports")
DEFAULT_TIMEZONE = "America/Los_Angeles"


@dataclass(frozen=True)
class AppConfig:
    userlist: Path = DEFAULT_USERLIST
    mock_data: Path = DEFAULT_MOCK_DATA
    reports_dir: Path = DEFAULT_REPORTS_DIR
    timezone: str = DEFAULT_TIMEZONE

    def resolved(self) -> AppConfig:
        return replace(self, userlist=Path(self.userlist).expanduser().resolve(),
                       mock_data=Path(self.mock_data).expanduser().resolve(),
                       reports_dir=Path(self.reports_dir).expanduser().resolve())

    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown reporting timezone {self.timezone!r}; "
                             "use an IANA name such as America/Los_Angeles") from exc
