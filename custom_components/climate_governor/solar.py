"""Solar budget helpers. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class SolarRoom:
    """A room that has a solar profile."""

    room_id: str
    priority: int
    load_w: float
    running: bool


class RollingAverage:
    """Time-windowed average of a power reading."""

    def __init__(self, window: timedelta) -> None:
        self._window = window
        self._samples: deque[tuple[datetime, float]] = deque()

    def add(self, when: datetime, value: float) -> None:
        """Record a reading."""
        self._samples.append((when, value))
        self._trim(when)

    def average(self, now: datetime) -> float | None:
        """Return the mean of readings inside the window, or None if empty."""
        self._trim(now)
        if not self._samples:
            return None
        return sum(v for _, v in self._samples) / len(self._samples)

    def _trim(self, now: datetime) -> None:
        cutoff = now - self._window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()


def solar_allowed(
    room_id: str,
    rooms: list[SolarRoom],
    avg_export_w: float | None,
    reserve_w: float,
) -> bool:
    """Decide whether a room may run on excess solar.

    The budget is the averaged export minus a reserve, plus the draw of rooms
    already running on solar (their load is already reflected in the export).
    Rooms claim the budget in priority order, lowest number first.
    """
    if avg_export_w is None:
        return False
    budget = avg_export_w - reserve_w + sum(r.load_w for r in rooms if r.running)
    used = 0.0
    for room in sorted(rooms, key=lambda r: (r.priority, r.room_id)):
        if room.room_id == room_id:
            return used + room.load_w <= budget
        if room.running:
            used += room.load_w
    return False
