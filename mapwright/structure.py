"""Section segmentation and the density curve.

The grid tells us *when* beats happen; this module decides *how intense* each
stretch of the song should be. It works on per-bar features (loudness and
onset activity), cuts the song where those features change, gives every
section a role, and maps the section energy onto a target note density.

Everything is snapped to **bars**, whose boundaries come from the grid and
therefore from the red lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .audio.base import AudioBuffer
from .timing.grid import Grid

#: analysis hop for the energy curve
HOP_SECONDS = 0.05

ROLES = ("intro", "verse", "chorus", "bridge", "outro")

#: a section is at most this long, so one long chorus is still one section
MAX_SECTION_BARS = 32


@dataclass
class BarFeature:
    start: int
    end: int
    loudness: float
    activity: float


@dataclass
class MusicSection:
    """A stretch of the song with a musical role and a target density."""

    start: int
    end: int
    role: str
    energy: float
    density: float
    sv: float = 1.0
    kiai: bool = False
    bars: int = 0
    index: int = 0

    @property
    def duration(self) -> int:
        return self.end - self.start

    def contains(self, time_ms: float) -> bool:
        return self.start <= time_ms < self.end

    def summary(self) -> str:
        flag = " kiai" if self.kiai else ""
        return (
            f"[{self.index:2d}] {self.role:7s} {self.start/1000:7.2f}s"
            f"-{self.end/1000:7.2f}s  bars={self.bars:3d}  "
            f"energy={self.energy:.2f}  nps={self.density:.2f}  sv={self.sv:.2f}{flag}"
        )


@dataclass
class DensityProfile:
    """How energy maps onto note density for a given difficulty."""

    min_nps: float = 0.5
    max_nps: float = 4.0
    #: >1 makes the curve flatter at low energy, then rise sharply
    gamma: float = 1.3
    #: density is eased across section boundaries over this many ms
    transition_ms: int = 900

    def __post_init__(self) -> None:
        if self.min_nps <= 0 or self.max_nps <= self.min_nps:
            raise ValueError("need 0 < min_nps < max_nps")

    def density_for(self, energy: float) -> float:
        energy = float(min(max(energy, 0.0), 1.0))
        return self.min_nps + (self.max_nps - self.min_nps) * energy**self.gamma


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------


def _energy_curve(audio: AudioBuffer, hop_seconds: float = HOP_SECONDS) -> tuple[np.ndarray, float]:
    """Frame-wise RMS and its positive first difference (attack activity)."""
    hop = max(1, int(audio.sample_rate * hop_seconds))
    samples = audio.samples
    count = max(1, len(samples) // hop)
    trimmed = samples[: count * hop].reshape(count, hop)
    rms = np.sqrt(np.mean(trimmed**2, axis=1) + 1e-12)
    activity = np.maximum(np.diff(rms, prepend=rms[0]), 0.0)
    return np.stack([rms, activity], axis=1).astype(np.float64), hop / audio.sample_rate


def bar_spans(grid: Grid, end_ms: int) -> list[tuple[int, int]]:
    """Bar boundaries as ``[start, end)`` pairs, following the meter."""
    spans: list[tuple[int, int]] = []
    beat = 0.0
    guard = 0
    while guard < 100_000:
        guard += 1
        start = grid.time_at_beat(beat)
        if start >= end_ms:
            break
        meter = grid.meter_at(start)
        nominal_end = grid.time_at_beat(beat + meter)
        end = min(nominal_end, end_ms)
        if end <= start:
            break
        # drop a trailing fragment: it is usually just encoder padding and
        # would otherwise become a tiny spurious section
        if end - start < 0.5 * (nominal_end - start):
            break
        spans.append((int(round(start)), int(round(end))))
        beat += meter
    return spans


def bar_features(
    audio: AudioBuffer, grid: Grid, end_ms: int | None = None
) -> list[BarFeature]:
    """Loudness and attack activity aggregated per bar."""
    end_ms = end_ms if end_ms is not None else int(audio.duration * 1000)
    curve, frame_seconds = _energy_curve(audio)
    spans = bar_spans(grid, end_ms)

    features: list[BarFeature] = []
    for start, end in spans:
        first = max(0, int(start / 1000.0 / frame_seconds))
        last = min(len(curve), max(first + 1, int(end / 1000.0 / frame_seconds)))
        window = curve[first:last]
        if len(window) == 0:
            continue
        features.append(
            BarFeature(
                start=start,
                end=end,
                loudness=float(window[:, 0].mean()),
                activity=float(window[:, 1].mean()),
            )
        )
    return features


def _robust_normalise(values: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return values
    low, high = np.percentile(values, 10), np.percentile(values, 90)
    if high - low <= 1e-9:
        return np.full_like(values, 0.5)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


# ---------------------------------------------------------------------------
# segmentation
# ---------------------------------------------------------------------------


def _novelty(features: np.ndarray, window: int) -> np.ndarray:
    """Distance between the mean feature on each side of every candidate cut."""
    count = len(features)
    scores = np.zeros(count)
    for index in range(window, count - window):
        left = features[index - window : index].mean(axis=0)
        right = features[index : index + window].mean(axis=0)
        denom = np.linalg.norm(left) + np.linalg.norm(right) + 1e-9
        scores[index] = float(np.linalg.norm(left - right) / denom)
    return scores


def detect_boundaries(
    features: list[BarFeature],
    *,
    min_bars: int = 4,
    threshold: float = 0.18,
    max_sections: int = 12,
) -> list[int]:
    """Bar indices where a new section starts (always includes 0)."""
    if not features:
        return [0]
    matrix = np.asarray(
        [[item.loudness, item.activity] for item in features], dtype=np.float64
    )
    normalised = np.stack(
        [_robust_normalise(matrix[:, 0]), _robust_normalise(matrix[:, 1])], axis=1
    )
    novelty = _novelty(normalised, window=2)

    peaks = [
        index
        for index in range(min_bars, len(features) - min_bars)
        if novelty[index] >= threshold
        and novelty[index] >= novelty[index - 1]
        and novelty[index] >= novelty[index + 1]
    ]
    peaks.sort(key=lambda index: novelty[index], reverse=True)

    chosen: list[int] = [0]
    for peak in peaks:
        if len(chosen) >= max_sections:
            break
        if all(abs(peak - existing) >= min_bars for existing in chosen):
            chosen.append(peak)
    chosen.sort()
    return chosen


def _assign_roles(sections: list[MusicSection]) -> None:
    if not sections:
        return
    energies = np.array([section.energy for section in sections])
    peak = float(energies.max()) or 1.0
    relative = energies / peak

    for position, section in enumerate(sections):
        section.role = "verse"

    # everything in the loudest quarter is a chorus
    for position, section in enumerate(sections):
        if relative[position] >= 0.75:
            section.role = "chorus"
    if not any(section.role == "chorus" for section in sections):
        sections[int(np.argmax(energies))].role = "chorus"

    last = len(sections) - 1
    if relative[0] <= 0.65 and sections[0].role != "chorus":
        sections[0].role = "intro"
    if relative[last] <= 0.65 and sections[last].role != "chorus":
        sections[last].role = "outro"

    # a quiet stretch that follows something louder is a bridge/breakdown
    for position, section in enumerate(sections):
        if not (0 < position < last):
            continue
        if relative[position] > 0.45:
            continue
        if relative[position] < relative[position - 1] - 0.1 and section.role == "verse":
            section.role = "bridge"


def _apply_kiai(sections: list[MusicSection], *, max_ratio: float = 0.4) -> None:
    """Mark the loudest sections as kiai, keeping the total under ``max_ratio``."""
    total = sum(section.duration for section in sections) or 1
    budget = total * max_ratio
    used = 0
    for section in sorted(sections, key=lambda item: item.energy, reverse=True):
        if section.role != "chorus":
            continue
        if used + section.duration > budget:
            continue
        section.kiai = True
        used += section.duration


def segment(
    audio: AudioBuffer,
    grid: Grid,
    *,
    profile: DensityProfile | None = None,
    end_ms: int | None = None,
) -> list[MusicSection]:
    """Split the song into sections snapped to bars, with a density target."""
    profile = profile or DensityProfile()
    end_ms = end_ms if end_ms is not None else int(audio.duration * 1000)

    features = bar_features(audio, grid, end_ms)
    if not features:
        return []

    cuts = detect_boundaries(features)
    cuts.append(len(features))

    loudness = np.array([item.loudness for item in features])
    energy_per_bar = _robust_normalise(loudness)

    sections: list[MusicSection] = []
    for index, (start_bar, end_bar) in enumerate(zip(cuts, cuts[1:])):
        if end_bar <= start_bar:
            continue
        section_energy = float(energy_per_bar[start_bar:end_bar].mean())
        section = MusicSection(
            start=features[start_bar].start,
            end=features[end_bar - 1].end,
            role="verse",
            energy=section_energy,
            density=profile.density_for(section_energy),
            bars=end_bar - start_bar,
            index=index,
        )
        sections.append(section)

    _assign_roles(sections)
    _apply_kiai(sections)

    for section in sections:
        # chorus slightly faster to read, bridge slightly slower
        offset = {"chorus": 0.1, "bridge": -0.1}.get(section.role, 0.0)
        section.sv = round(float(np.clip(0.9 + 0.2 * section.energy + offset, 0.8, 1.25)), 2)

    return sections


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


@dataclass
class SectionMap:
    """Sections plus the eased density lookup used by the rhythm stage."""

    sections: list[MusicSection] = field(default_factory=list)
    transition_ms: int = 900

    def section_at(self, time_ms: float) -> MusicSection | None:
        for section in self.sections:
            if section.contains(time_ms):
                return section
        return self.sections[-1] if self.sections else None

    def density_at(self, time_ms: float) -> float:
        """Target NPS, eased across section boundaries."""
        if not self.sections:
            return 0.0
        section = self.section_at(time_ms)
        if section is None:
            return 0.0
        position = self.sections.index(section)
        neighbour = self.sections[position - 1] if position > 0 else None
        following = (
            self.sections[position + 1] if position + 1 < len(self.sections) else None
        )

        window = max(1, self.transition_ms)
        if neighbour is not None and time_ms - section.start < window:
            ratio = (time_ms - section.start) / window
            return neighbour.density + (section.density - neighbour.density) * ratio
        if following is not None and section.end - time_ms < window:
            ratio = (section.end - time_ms) / window
            return section.density + (following.density - section.density) * (1 - ratio)
        return section.density

    @property
    def duration(self) -> int:
        if not self.sections:
            return 0
        return self.sections[-1].end - self.sections[0].start

    @property
    def kiai_duration(self) -> int:
        return sum(section.duration for section in self.sections if section.kiai)

    def table(self) -> str:
        return "\n".join(section.summary() for section in self.sections)
