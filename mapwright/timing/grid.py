"""Beat grid derived from red lines.

The grid is **not stored** in the file — it is recomputed from the red lines.
This module is the single place that implements the mapping between absolute
milliseconds and musical positions::

    grid = Grid(beatmap.red_lines())
    grid.time_at_beat(4)            # start of beat 4
    grid.ticks(0, 10_000, 4)        # every 1/4 within the first 10 seconds
    grid.snap(1_037, 4)             # nearest 1/4 tick

Everything is anchored on the first red line; beats are counted continuously
across tempo changes, and each red line restarts the *bar* count.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from ..osu.model import TimingPoint

_EPSILON = 1e-9


@dataclass
class Grid:
    """Piecewise-constant beat mapping built from red lines."""

    red_lines: list[TimingPoint]
    #: cumulative beat index at the start of each red line's section
    _beat_offsets: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not self.red_lines:
            raise ValueError("a grid needs at least one red line")
        if any(point.uninherited is False for point in self.red_lines):
            raise ValueError("grid only accepts red (uninherited) points")
        self.red_lines = sorted(self.red_lines, key=lambda point: point.time)
        self._beat_offsets = [0.0]
        for previous, current in zip(self.red_lines, self.red_lines[1:]):
            if current.beat_length <= 0:
                raise ValueError("red lines must have a positive beat length")
            beats = (current.time - previous.time) / previous.beat_length
            self._beat_offsets.append(self._beat_offsets[-1] + beats)

    # -- construction -------------------------------------------------------

    @classmethod
    def from_timing_points(cls, points: Iterable[TimingPoint]) -> "Grid":
        reds = [point for point in points if point.uninherited]
        return cls(reds)

    # -- lookups ------------------------------------------------------------

    @property
    def start(self) -> int:
        return self.red_lines[0].time

    @property
    def beat_length(self) -> float:
        return self.red_lines[0].beat_length

    def _section_at_time(self, time_ms: float) -> int:
        index = 0
        for position, point in enumerate(self.red_lines):
            if point.time <= time_ms + _EPSILON:
                index = position
            else:
                break
        return index

    def _section_at_beat(self, beat: float) -> int:
        index = 0
        for position, offset in enumerate(self._beat_offsets):
            if offset <= beat + _EPSILON:
                index = position
            else:
                break
        return index

    def bpm_at(self, time_ms: float) -> float:
        point = self.red_lines[self._section_at_time(time_ms)]
        return 60000.0 / point.beat_length

    def meter_at(self, time_ms: float) -> int:
        return self.red_lines[self._section_at_time(time_ms)].meter

    def beat_length_at(self, time_ms: float) -> float:
        return self.red_lines[self._section_at_time(time_ms)].beat_length

    def beat_index(self, time_ms: float) -> float:
        """Continuous beat position of ``time_ms`` (0 = first red line)."""
        section = self._section_at_time(time_ms)
        point = self.red_lines[section]
        return self._beat_offsets[section] + (time_ms - point.time) / point.beat_length

    def time_at_beat(self, beat: float) -> float:
        """Inverse of :meth:`beat_index`."""
        section = self._section_at_beat(beat)
        point = self.red_lines[section]
        return point.time + (beat - self._beat_offsets[section]) * point.beat_length

    # -- snapping -----------------------------------------------------------

    def ticks(
        self,
        start_ms: float,
        end_ms: float,
        divisor: int,
        *,
        include_end: bool = True,
    ) -> list[int]:
        """All tick times in ``[start_ms, end_ms]`` for the given divisor.

        ``divisor`` is the beat-snap divisor: 4 means 1/4 (four ticks per beat).
        """
        if divisor <= 0:
            raise ValueError("divisor must be positive")
        if end_ms < start_ms:
            raise ValueError("end_ms must not be before start_ms")

        first = math.ceil(self.beat_index(start_ms) * divisor - _EPSILON)
        last = math.floor(self.beat_index(end_ms) * divisor + _EPSILON)

        ticks: list[int] = []
        for index in range(first, last + 1):
            time_ms = int(round(self.time_at_beat(index / divisor)))
            if time_ms < start_ms - 0.5:
                continue
            if time_ms > end_ms + (0.5 if include_end else -0.5):
                continue
            ticks.append(time_ms)
        return ticks

    def snap(self, time_ms: float, divisor: int) -> int:
        """Nearest tick time for ``time_ms``."""
        if divisor <= 0:
            raise ValueError("divisor must be positive")
        position = self.beat_index(time_ms) * divisor
        return int(round(self.time_at_beat(round(position) / divisor)))

    def is_snapped(self, time_ms: float, divisor: int, tolerance_ms: float = 1.0) -> bool:
        return abs(self.snap(time_ms, divisor) - time_ms) <= tolerance_ms

    def nearest_beat(self, time_ms: float) -> int:
        return int(round(self.beat_index(time_ms)))

    def bar_start(self, time_ms: float) -> int:
        """Start of the bar containing ``time_ms`` (uses each red line's meter)."""
        section = self._section_at_time(time_ms)
        point = self.red_lines[section]
        beats_into_section = self.beat_index(time_ms) - self._beat_offsets[section]
        bar_index = int(beats_into_section // point.meter)
        return int(round(point.time + bar_index * point.meter * point.beat_length))


def beats_per_second(bpm: float, divisor: int = 4) -> float:
    """Note density if every tick of ``divisor`` were filled."""
    return bpm / 60.0 * divisor


@dataclass
class Section:
    """A time span with the musical context derived from the grid."""

    start: int
    end: int
    bpm: float
    meter: int = 4

    @property
    def duration(self) -> int:
        return self.end - self.start

    @property
    def beats(self) -> float:
        return self.duration / (60000.0 / self.bpm)


def sections_from_grid(grid: Grid, end_time: int) -> list[Section]:
    """Split ``[grid.start, end_time]`` at every red line."""
    sections: list[Section] = []
    for position, point in enumerate(grid.red_lines):
        if point.time > end_time:
            break
        next_time = (
            grid.red_lines[position + 1].time
            if position + 1 < len(grid.red_lines)
            else end_time
        )
        sections.append(
            Section(
                start=point.time,
                end=min(next_time, end_time),
                bpm=60000.0 / point.beat_length,
                meter=point.meter,
            )
        )
    return sections
