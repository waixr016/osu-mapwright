"""Learn the song's own accent pattern instead of hard-coding one.

A typical 4/4 pop track puts the kick on beats 1 and 3 and the snare on 2 and
4. Rather than baking that in, we measure it: for every position inside a bar,
average the onset salience of that position across the whole song. The result
is a per-band accent profile that automatically adapts to 3/4, half-time,
reggaeton or double-kick sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..audio.onsets import SalienceCurves
from ..timing.grid import Grid


@dataclass
class AccentTemplate:
    """Per-position accent weights, plus the per-band breakdown."""

    meter: int
    subdivision: int
    weights: dict[int, float] = field(default_factory=dict)
    band_weights: dict[str, dict[int, float]] = field(default_factory=dict)

    @property
    def positions(self) -> int:
        return self.meter * self.subdivision

    def weight(self, position: int) -> float:
        """Accent for a position inside the bar (0..positions-1)."""
        if not self.weights:
            return 1.0
        return self.weights.get(position % self.positions, 0.5)

    def band_weight(self, band: str, position: int) -> float:
        values = self.band_weights.get(band, {})
        return values.get(position % self.positions, 0.5)

    @classmethod
    def build(
        cls,
        salience: SalienceCurves,
        grid: Grid,
        *,
        phase: int = 0,
        meter: int = 4,
        subdivision: int = 2,
        end_ms: int | None = None,
        band_weights: dict[str, float] | None = None,
    ) -> "AccentTemplate":
        positions = meter * subdivision
        mixing = band_weights or {"low": 1.0, "mid": 0.6, "high": 0.3}
        sums = {band: np.zeros(positions) for band in salience.bands}
        counts = np.zeros(positions)

        if not grid.red_lines:
            return cls(meter=meter, subdivision=subdivision)

        end_ms = end_ms if end_ms is not None else int(salience.times_ms[-1]) if len(salience) else 0
        beat = 0.0
        guard = 0
        while guard < 1_000_000:
            guard += 1
            time_ms = grid.time_at_beat(beat)
            if time_ms >= end_ms:
                break
            relative = beat - phase
            position = int((relative * subdivision) + 0.5) % positions
            values = salience.at(time_ms)
            for band, value in values.items():
                sums[band][position] += value
            counts[position] += 1
            beat += 1.0 / subdivision

        weights: dict[int, float] = {}
        band_weights_result: dict[str, dict[int, float]] = {}
        for position in range(positions):
            # the low band dominates: kicks define the pulse, broadband snares
            # would otherwise outvote them purely on total energy
            weights[position] = sum(
                sums[band][position] * mixing.get(band, 0.0)
                for band in sums
            ) / max(counts[position], 1)
        peak = max(weights.values()) if weights else 0.0
        if peak > 0:
            weights = {key: value / peak for key, value in weights.items()}

        for band, values in sums.items():
            averaged = {
                position: float(values[position] / max(counts[position], 1))
                for position in range(positions)
            }
            band_peak = max(averaged.values()) if averaged else 0.0
            band_weights_result[band] = {
                key: (value / band_peak if band_peak > 0 else 0.0)
                for key, value in averaged.items()
            }

        return cls(
            meter=meter,
            subdivision=subdivision,
            weights=weights,
            band_weights=band_weights_result,
        )

    def summary(self) -> str:
        rows = []
        for position in range(self.positions):
            rows.append(f"{position}:{self.weights.get(position, 0.0):.2f}")
        return " ".join(rows)
