"""Calendar based employee activity aggregation."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .models import Changelist, Employee


@dataclass(frozen=True)
class EmployeeCount:
    employee: Employee
    count: int


@dataclass(frozen=True)
class ReportStats:
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    weekly: tuple[EmployeeCount, ...]
    monthly: tuple[EmployeeCount, ...]
    yearly: tuple[EmployeeCount, ...]
    mapped: tuple[tuple[Changelist, Employee], ...]
    unmapped: tuple[Changelist, ...]
    all_weekly_total: int
    all_monthly_total: int
    all_yearly_total: int

    @property
    def weekly_total(self) -> int: return self.all_weekly_total
    @property
    def monthly_total(self) -> int: return self.all_monthly_total
    @property
    def yearly_total(self) -> int: return self.all_yearly_total
    @property
    def zero_weekly(self) -> int: return sum(x.count == 0 for x in self.weekly)


def calculate_statistics(employees: list[Employee], changelists: list[Changelist],
                         as_of: datetime, timezone: ZoneInfo) -> ReportStats:
    now = as_of.astimezone(timezone)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    by_user = {employee.username: employee for employee in employees}
    counts = [{employee.username: 0 for employee in employees} for _ in range(3)]
    totals = [0, 0, 0]
    mapped, unmapped = [], []
    for change in changelists:
        stamp = change.timestamp.astimezone(timezone)
        in_week = week_start <= stamp < week_end and stamp <= now
        in_month = month_start <= stamp <= now
        in_year = year_start <= stamp <= now
        totals[0] += in_week
        totals[1] += in_month
        totals[2] += in_year
        employee = by_user.get(change.user)
        if employee is None:
            unmapped.append(change)
            continue
        mapped.append((change, employee))
        if in_week:
            counts[0][employee.username] += 1
        if in_month:
            counts[1][employee.username] += 1
        if in_year:
            counts[2][employee.username] += 1
    def ordered(bucket: dict[str, int]) -> tuple[EmployeeCount, ...]:
        return tuple(sorted((EmployeeCount(e, bucket[e.username]) for e in employees),
                            key=lambda x: (-x.count, x.employee.name.casefold())))
    return ReportStats(now, week_start, week_end - timedelta(microseconds=1),
                       ordered(counts[0]), ordered(counts[1]), ordered(counts[2]),
                       tuple(sorted(mapped, key=lambda row: row[0].timestamp)),
                       tuple(sorted(unmapped, key=lambda c: c.timestamp)), *totals)
