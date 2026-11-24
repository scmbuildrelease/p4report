"""Calendar-based changelist aggregation.

Reporting policy (all boundaries in the reporting timezone, all intervals
half-open ``[start, end)``, all comparisons made on absolute UTC instants so
DST transitions cannot reorder events):

* Weekly  - the previous complete week: Monday 00:00 up to this Monday 00:00.
* Monthly - the 1st of the current month 00:00 up to the generation time.
* Yearly  - January 1 of the current year 00:00 up to the generation time.

Ranking policy: count descending, then employee name (case-insensitive, then
username for identical names); equal counts share a rank and the next rank
skips ("competition" ranking: 1, 1, 3).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from .models import Changelist, Employee, normalize_username

PERIOD_KEYS = ("week", "month", "year")


@dataclass(frozen=True)
class Period:
    key: str
    title: str
    start: datetime
    end: datetime
    description: str

    def contains(self, stamp: datetime) -> bool:
        instant = stamp.astimezone(UTC)
        return self.start.astimezone(UTC) <= instant < self.end.astimezone(UTC)


def _midnight(day: date, zone: tzinfo) -> datetime:
    return datetime.combine(day, time(), tzinfo=zone)


def reporting_periods(as_of: datetime, zone: tzinfo) -> tuple[Period, Period, Period]:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    now = as_of.astimezone(zone)
    today = now.date()
    this_monday = today - timedelta(days=today.weekday())
    week = Period("week", "Weekly", _midnight(this_monday - timedelta(days=7), zone),
                  _midnight(this_monday, zone), "Previous complete week, Monday 00:00 to Monday 00:00")
    month = Period("month", "Monthly", _midnight(today.replace(day=1), zone), now,
                   "Current month to date, 1st 00:00 to report generation time")
    year = Period("year", "Yearly", _midnight(today.replace(month=1, day=1), zone), now,
                  "Current year to date, January 1 00:00 to report generation time")
    return week, month, year


@dataclass(frozen=True)
class RankedCount:
    rank: int
    employee: Employee
    count: int


@dataclass(frozen=True)
class PeriodStats:
    period: Period
    ranking: tuple[RankedCount, ...]
    mapped: int
    unmapped: int

    @property
    def total(self) -> int:
        return self.mapped + self.unmapped

    @property
    def zero_employees(self) -> int:
        return sum(row.count == 0 for row in self.ranking)


@dataclass(frozen=True)
class ChangeRow:
    change: Changelist
    employee: Employee | None
    local_time: datetime
    in_week: bool
    in_month: bool
    in_year: bool


@dataclass(frozen=True)
class UnmappedUser:
    username: str
    week: int
    month: int
    year: int
    changes: tuple[int, ...]


@dataclass(frozen=True)
class ReportStats:
    generated_at: datetime
    timezone_name: str
    week: PeriodStats
    month: PeriodStats
    year: PeriodStats
    employee_count: int
    rows: tuple[ChangeRow, ...]
    unmapped_users: tuple[UnmappedUser, ...]

    @property
    def periods(self) -> tuple[PeriodStats, PeriodStats, PeriodStats]:
        return self.week, self.month, self.year


def rank(employees: list[Employee], counts: dict[str, int]) -> tuple[RankedCount, ...]:
    ordered = sorted(employees, key=lambda e: (-counts[e.key], e.name.casefold(), e.name, e.key))
    result: list[RankedCount] = []
    for position, employee in enumerate(ordered, 1):
        count = counts[employee.key]
        same_as_previous = result and result[-1].count == count
        result.append(RankedCount(result[-1].rank if same_as_previous else position, employee, count))
    return tuple(result)


def calculate_statistics(employees: list[Employee], changelists: list[Changelist],
                         as_of: datetime, zone: tzinfo) -> ReportStats:
    periods = reporting_periods(as_of, zone)
    by_user: dict[str, Employee] = {}
    for person in employees:
        if person.key in by_user:
            raise ValueError(f"duplicate Perforce username {person.username!r}")
        by_user[person.key] = person
    seen: set[int] = set()
    counts = {p.key: {e.key: 0 for e in employees} for p in periods}
    mapped = dict.fromkeys(PERIOD_KEYS, 0)
    unmapped = dict.fromkeys(PERIOD_KEYS, 0)
    orphans: dict[str, dict[str, int]] = {}
    orphan_changes: dict[str, list[int]] = {}
    orphan_names: dict[str, str] = {}
    rows: list[ChangeRow] = []
    for change in changelists:
        if change.change in seen:
            raise ValueError(f"duplicate changelist number {change.change} from data source")
        seen.add(change.change)
        flags = {p.key: p.contains(change.timestamp) for p in periods}
        key = normalize_username(change.user)
        employee = by_user.get(key)
        if employee is None:
            orphan_names.setdefault(key, change.user)
            orphan_changes.setdefault(key, []).append(change.change)
        bucket = orphans.setdefault(key, dict.fromkeys(PERIOD_KEYS, 0)) if employee is None else None
        for period_key, inside in flags.items():
            if not inside:
                continue
            if bucket is not None:
                unmapped[period_key] += 1
                bucket[period_key] += 1
            elif employee is not None:
                mapped[period_key] += 1
                counts[period_key][employee.key] += 1
        rows.append(ChangeRow(change, employee, change.timestamp.astimezone(zone),
                              flags["week"], flags["month"], flags["year"]))
    week, month, year = (PeriodStats(p, rank(employees, counts[p.key]), mapped[p.key], unmapped[p.key])
                         for p in periods)
    unmapped_users = tuple(sorted(
        (UnmappedUser(orphan_names[k], v["week"], v["month"], v["year"], tuple(sorted(orphan_changes[k])))
         for k, v in orphans.items()),
        key=lambda u: (-u.year, u.username.casefold())))
    rows.sort(key=lambda r: (r.change.timestamp.astimezone(UTC), r.change.change))
    return ReportStats(as_of.astimezone(zone), getattr(zone, "key", str(zone)), week, month, year,
                       len(employees), tuple(rows), unmapped_users)
