"""Perforce data source abstraction."""
from datetime import datetime
from typing import Protocol
from .models import Changelist


class P4Client(Protocol):
    def get_changelists(self, as_of: datetime) -> list[Changelist]:
        """Return changelists visible to the report."""
