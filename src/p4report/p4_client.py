"""Perforce data source abstraction.

The reporting flow depends only on this protocol, so a private deployment can
supply its own implementation (for example one backed by ``p4 changes``)
through ``cli.main(client_factory=...)`` without touching statistics, Excel or
email code. This public project deliberately ships no real Perforce client.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import Changelist


@runtime_checkable
class P4Client(Protocol):
    def get_changelists(self, start: datetime, end: datetime) -> list[Changelist]:
        """Return submitted changelists with ``start <= timestamp < end``.

        ``start`` and ``end`` are timezone-aware. Returned timestamps must be
        timezone-aware; any zone is accepted and converted by the report.
        """
        ...


# Builds a client from the ``--data`` path and the report reference time.
ClientFactory = Callable[[Path, datetime], P4Client]
