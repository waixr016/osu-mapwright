"""Turning a :class:`~mapwright.audio.base.TempoEstimate` into red lines.

A red line is a *measurement*, not a design decision: one line is written per
constant-tempo stretch, and nothing else. Green lines are produced much later,
from section-level design intent (see ``mapwright.timing.sections``).
"""

from __future__ import annotations

import math

from ..audio.base import TempoEstimate
from ..osu.model import Beatmap, TimingPoint

#: osu!'s default sample sets
SAMPLE_SET_NORMAL = 1
SAMPLE_SET_SOFT = 2
SAMPLE_SET_DRUM = 3


def red_lines_from_estimate(
    estimate: TempoEstimate,
    *,
    meter: int = 4,
    sample_set: int = SAMPLE_SET_NORMAL,
    volume: int = 80,
    kiai: bool = False,
) -> list[TimingPoint]:
    """Build the red lines for a constant-tempo song.

    The offset is kept where the first beat actually is (only pushed forward
    if it would land before the audio starts), so that beat 0 of the grid and
    ``estimate.downbeat_phase`` refer to the same beat.
    """
    if estimate.bpm <= 0:
        raise ValueError("bpm must be positive")
    beat_ms = 60000.0 / estimate.bpm
    offset = estimate.offset_ms
    if offset < 0:
        offset += beat_ms * math.ceil(-offset / beat_ms)
    return [
        TimingPoint.red(
            time=int(round(offset)),
            bpm=estimate.bpm,
            meter=meter,
            sample_set=sample_set,
            volume=volume,
            kiai=kiai,
        )
    ]


def apply_red_lines(
    beatmap: Beatmap,
    red_lines: list[TimingPoint],
    *,
    keep_green_lines: bool = True,
) -> Beatmap:
    """Replace the red lines of ``beatmap`` while keeping existing green lines."""
    greens = [
        point
        for point in beatmap.timing_points
        if not point.uninherited and keep_green_lines
    ]
    beatmap.timing_points = sorted(
        [*red_lines, *greens], key=lambda point: (point.time, not point.uninherited)
    )
    return beatmap


def validate(red_lines: list[TimingPoint]) -> list[str]:
    """Structural checks for a red-line list."""
    problems: list[str] = []
    if not red_lines:
        problems.append("no red lines")
        return problems
    if any(point.uninherited is False for point in red_lines):
        problems.append("a green line was passed as a red line")
    if any(point.beat_length <= 0 for point in red_lines):
        problems.append("red line with non-positive beat length")
    for previous, current in zip(red_lines, red_lines[1:]):
        if current.time <= previous.time:
            problems.append("red lines are not strictly increasing in time")
    first_bpm = 60000.0 / red_lines[0].beat_length
    if not (1.0 < first_bpm < 1000.0):
        problems.append(f"implausible BPM: {first_bpm:.2f}")
    return problems
