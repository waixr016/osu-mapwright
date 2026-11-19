"""Choose *which* grid ticks become notes.

The score for a tick is ``salience ** a * accent ** b``: salience says "there
is a sound here", the accent template says "this position in the bar usually
carries a sound". Selection is done bar by bar with a fractional budget so the
density stays close to the section target without becoming metronomic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..audio.onsets import SalienceCurves
from ..structure import MusicSection
from ..timing.grid import Grid
from .accent import AccentTemplate


@dataclass
class RhythmEvent:
    """A note placed in time; the geometry stage decides where it goes."""

    time: int
    beat: float
    position: int
    strength: float
    salience: float

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RhythmEvent(t={self.time}, beat={self.beat:.2f}, s={self.strength:.2f})"


@dataclass
class RhythmConfig:
    #: grid divisor: 4 means 1/4 notes
    divisor: int = 4
    #: accent resolution: 2 means the template has eight positions in 4/4
    subdivision: int = 2
    max_nps: float = 12.0
    salience_power: float = 1.0
    accent_power: float = 0.85
    #: ticks scoring below this are never used
    threshold: float = 0.05
    #: salience window around a tick
    window_ms: float = 20.0
    #: low band counts double: kicks define the skeleton
    band_weights: dict[str, float] = field(
        default_factory=lambda: {"low": 1.0, "mid": 0.9, "high": 0.6}
    )
    #: metrical tie-breaker. Energy cannot tell beat 1 from beat 2 — a loud
    #: snare outranks a soft kick — so the meter hierarchy is applied as a
    #: separate, adjustable multiplier. Set all three to 1.0 to disable.
    downbeat_prior: float = 1.4
    beat_prior: float = 1.0
    offbeat_prior: float = 0.85
    #: a bar with a single note should start on the downbeat, as long as that
    #: downbeat actually carries a sound (this is charting convention, not a
    #: measurement: energy cannot rank metrical positions)
    anchor_sparse_bars: bool = True
    anchor_threshold: float = 0.4

    def __post_init__(self) -> None:
        if self.divisor <= 0:
            raise ValueError("divisor must be positive")
        if self.subdivision <= 0:
            raise ValueError("subdivision must be positive")

    def metrical_prior(self, position: int) -> float:
        if position % self.subdivision != 0:
            return self.offbeat_prior
        beat_in_bar = position // self.subdivision
        return self.downbeat_prior if beat_in_bar == 0 else self.beat_prior


def _round_half_up(value: float) -> int:
    """``round()`` is banker's rounding: 0.5 -> 0, 1.5 -> 2. Not what we want."""
    return int(math.floor(value + 0.5))


def _salience_of(
    salience: SalienceCurves, time_ms: float, weights: dict[str, float], window_ms: float
) -> float:
    values = salience.at(time_ms, window_ms)
    return float(sum(values.get(band, 0.0) * weight for band, weight in weights.items()))


def generate_rhythm(
    sections: list[MusicSection],
    grid: Grid,
    salience: SalienceCurves,
    accent: AccentTemplate,
    *,
    phase: int = 0,
    config: RhythmConfig | None = None,
) -> list[RhythmEvent]:
    """Return the chosen notes, sorted by time and snapped to the grid."""
    config = config or RhythmConfig()
    positions = accent.positions

    events: list[RhythmEvent] = []
    for section in sections:
        if section.duration <= 0:
            continue
        ticks = grid.ticks(section.start, section.end, config.divisor, include_end=False)
        if not ticks:
            continue

        candidates: dict[int, list[RhythmEvent]] = {}
        for tick in ticks:
            beat = grid.beat_index(tick)
            position = _round_half_up(
                beat * config.subdivision - phase * config.subdivision
            ) % positions
            raw = _salience_of(salience, tick, config.band_weights, config.window_ms)
            strength = (
                (max(raw, 0.0) ** config.salience_power)
                * (max(accent.weight(position), 0.0) ** config.accent_power)
                * config.metrical_prior(position)
            )
            if strength < config.threshold:
                continue
            event = RhythmEvent(
                time=tick,
                beat=beat,
                position=position,
                strength=float(strength),
                salience=float(raw),
            )
            bar = int(math.floor((beat - phase) / grid.meter_at(tick)))
            candidates.setdefault(bar, []).append(event)

        carry = 0.0
        for bar in sorted(candidates):
            pool = candidates[bar]
            bar_ms = grid.meter_at(pool[0].time) * grid.beat_length_at(pool[0].time)
            target = section.density * bar_ms / 1000.0
            carry += target
            wanted = int(math.floor(carry + 1e-9))
            carry -= wanted

            cap = max(0.0, config.max_nps * bar_ms / 1000.0)
            count = int(min(wanted, len(pool), math.floor(cap + 1e-9)))
            if count <= 0:
                continue

            pool.sort(key=lambda item: item.strength, reverse=True)
            chosen = pool[:count]
            if config.anchor_sparse_bars and count == 1 and chosen[0].position != 0:
                downbeats = [item for item in pool if item.position == 0]
                if downbeats:
                    best = max(downbeats, key=lambda item: item.salience)
                    if best.salience >= config.anchor_threshold * chosen[0].salience:
                        chosen = [best]
            events.extend(chosen)

    events.sort(key=lambda item: item.time)
    return events


def rhythm_statistics(events: list[RhythmEvent], duration_ms: int) -> dict[str, float]:
    """Handy numbers for tests, logs and the preview map."""
    if not events:
        return {"notes": 0, "nps": 0.0, "on_beat_ratio": 0.0}
    on_beat = sum(1 for event in events if event.position % 2 == 0)
    return {
        "notes": float(len(events)),
        "nps": len(events) / max(duration_ms / 1000.0, 1e-6),
        "on_beat_ratio": on_beat / len(events),
    }
