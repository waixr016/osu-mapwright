"""Per-band onset salience.

A single broadband onset curve cannot tell a kick from a hi-hat; splitting the
spectrum into three bands lets the rhythm stage ask "is there low-frequency
energy on this downbeat" instead of "is anything happening here".

Frames are converted to milliseconds with the STFT padding taken into account,
so the curve lines up with the beat grid instead of leading it by ~23 ms.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .base import ANALYSIS_SR, AudioBuffer
from .dsp import DEFAULT_HOP, DEFAULT_N_FFT, flux, frame_times_ms, robust_normalise, stft_magnitude

#: band edges in Hz
BANDS: dict[str, tuple[float, float]] = {
    "low": (20.0, 150.0),
    "mid": (150.0, 2000.0),
    "high": (2000.0, 8000.0),
}


@dataclass
class SalienceCurves:
    """Normalised per-band onset strength over time."""

    times_ms: np.ndarray
    bands: dict[str, np.ndarray]

    def at(self, time_ms: float, window_ms: float = 20.0) -> dict[str, float]:
        """Peak salience of each band inside ``time_ms ± window_ms``."""
        half = max(1, int(round(window_ms)))
        first = int(np.searchsorted(self.times_ms, time_ms - half, side="left"))
        last = int(np.searchsorted(self.times_ms, time_ms + half, side="right"))
        if first >= last:
            index = int(
                np.clip(np.searchsorted(self.times_ms, time_ms), 0, len(self.times_ms) - 1)
            )
            return {name: float(values[index]) for name, values in self.bands.items()}
        return {
            name: float(values[first:last].max())
            for name, values in self.bands.items()
        }

    def total(self, time_ms: float, window_ms: float = 20.0) -> float:
        return float(sum(self.at(time_ms, window_ms).values()))

    def __len__(self) -> int:
        return len(self.times_ms)


class SalienceExtractor:
    """Compute :class:`SalienceCurves` for an audio buffer."""

    def __init__(
        self,
        audio: AudioBuffer,
        *,
        sample_rate: int = ANALYSIS_SR,
        n_fft: int = DEFAULT_N_FFT,
        hop: int = DEFAULT_HOP,
    ) -> None:
        analysed = audio.resample(sample_rate)
        self.sample_rate = analysed.sample_rate
        self.n_fft = n_fft
        self.hop = hop

        magnitudes = stft_magnitude(analysed.samples, n_fft=n_fft, hop=hop)
        frequencies = np.fft.rfftfreq(n_fft, 1.0 / analysed.sample_rate)

        bands: dict[str, np.ndarray] = {}
        for name, (low, high) in BANDS.items():
            mask = (frequencies >= low) & (frequencies < high)
            if not mask.any():
                bands[name] = np.zeros(magnitudes.shape[0], dtype=np.float64)
                continue
            bands[name] = robust_normalise(flux(magnitudes[:, mask]).astype(np.float64))

        self.curves = SalienceCurves(
            times_ms=frame_times_ms(magnitudes.shape[0], hop, analysed.sample_rate, n_fft),
            bands=bands,
        )

    def at(self, time_ms: float, window_ms: float = 20.0) -> dict[str, float]:
        return self.curves.at(time_ms, window_ms)

    def total(self, time_ms: float, window_ms: float = 20.0) -> float:
        return self.curves.total(time_ms, window_ms)

    def __len__(self) -> int:
        return len(self.curves)
