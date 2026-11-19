"""Optional tempo estimator backed by librosa.

Kept behind the same :class:`~mapwright.audio.base.TempoEstimator` interface so
it can be swapped in without touching the rest of the pipeline::

    pip install librosa soundfile
    estimator = get_estimator("librosa")

librosa is imported at module import time on purpose: if it is missing this
module raises ``ImportError`` and :func:`mapwright.audio.get_estimator` falls
back to the numpy backend.
"""

from __future__ import annotations

import numpy as np

try:  # pragma: no cover - exercised only when librosa is installed
    import librosa
except ImportError:  # pragma: no cover
    raise ImportError("librosa is not installed") from None

from .base import AudioBuffer, TempoEstimate, downbeat_phase


class LibrosaTempoEstimator:  # pragma: no cover - requires librosa
    """Beat tracking via librosa, with numpy post-processing for the offset."""

    name = "librosa"

    def __init__(
        self,
        meter: int = 4,
        hop_length: int = 512,
        preferred_bpm: float = 120.0,
        min_bpm: float = 60.0,
        max_bpm: float = 240.0,
    ) -> None:
        self.meter = meter
        self.hop_length = hop_length
        self.preferred_bpm = preferred_bpm
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm

    def estimate(self, audio: AudioBuffer) -> TempoEstimate:
        if audio.duration < 2.0:
            raise ValueError("audio must be at least 2 seconds long")

        samples = np.ascontiguousarray(audio.samples, dtype=np.float32)
        sample_rate = audio.sample_rate
        hop = self.hop_length

        onset_envelope = librosa.onset.onset_strength(
            y=samples, sr=sample_rate, hop_length=hop
        )
        tempo, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_envelope,
            sr=sample_rate,
            hop_length=hop,
            start_bpm=self.preferred_bpm,
            tightness=100,
        )
        frames = np.atleast_1d(beat_frames)
        if len(frames) < 4:
            raise ValueError("librosa found too few beats")

        times = librosa.frames_to_time(frames, sr=sample_rate, hop_length=hop) * 1000.0

        # least squares fit: beat k happens at intercept + slope * k
        index = np.arange(len(times), dtype=np.float64)
        design = np.stack([np.ones_like(index), index], axis=1)
        (intercept, slope), *_ = np.linalg.lstsq(design, times, rcond=None)
        if slope <= 0:
            raise ValueError("librosa produced a non-positive beat length")

        fitted = intercept + index * slope
        residual = float(np.median(np.abs(times - fitted)))
        beat_ms = float(slope)
        bpm = 60000.0 / beat_ms
        offset_ms = float(intercept) % beat_ms

        frames_per_second = sample_rate / hop
        low_envelope = librosa.onset.onset_strength(
            y=samples, sr=sample_rate, hop_length=hop, fmin=20, fmax=150
        )
        beat_times = self._beat_times(offset_ms, beat_ms, audio.duration)
        phase = downbeat_phase(low_envelope, frames_per_second, beat_times, self.meter)
        confidence = float(np.clip(1.0 - residual / (beat_ms * 0.5), 0.0, 1.0))

        return TempoEstimate(
            bpm=float(bpm),
            offset_ms=offset_ms,
            downbeat_phase=phase,
            confidence=confidence,
            residual_ms=residual,
            beat_times=beat_times,
            duration=audio.duration,
            source=self.name,
        )

    @staticmethod
    def _beat_times(offset_ms: float, beat_ms: float, duration: float) -> list[float]:
        count = int((duration * 1000.0 - offset_ms) // beat_ms) + 1
        count = max(0, min(count, 100_000))
        return [offset_ms + index * beat_ms for index in range(count)]
