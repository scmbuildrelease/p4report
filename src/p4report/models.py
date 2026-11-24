"""Typed data models for employee and changelist records."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Employee:
    name: str
    email: str
    username: str


@dataclass(frozen=True)
class Changelist:
    change: int
    user: str
    timestamp: datetime
    description: str
    files: tuple[str, ...]
