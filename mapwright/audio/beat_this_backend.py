"""Beat This! backend (ISMIR 2024).

Beat This! is a transformer beat/downbeat tracker. Compared to the numpy
backend it needs torch plus an 8-78 MB checkpoint, but it is far more accurate
on real music and gives us the *downbeats* directly instead of guessing them
from low-frequency accents.

Install::

    pip install beat-this            # pulls torch, torchaudio, einops, soxr

The module raises ``ImportError`` when the package is missing so that
:func:`mapwright.audio.get_estimator` can fall back to another backend.
"""

from __future__ import annotations

import uuid
import wave
from pathlib import Path

import numpy as np

try:  # pragma: no cover - depends on the environment
    import beat_this  # noqa: F401  (probe only)
except ImportError:  # pragma: no cover
    raise ImportError("beat_this is not installed") from None

from .base import AudioBuffer, TempoEstimate


class BeatThisEstimator:  # pragma: no cover - requires beat_this + torch
    """Beat and downbeat tracking with the Beat This! transformer."""

    name = "beat_this"

    def __init__(
        self,
        model: str = "small0",
        device: str = "cpu",
        meter: int = 4,
        scratch_dir: str | Path = "build",
    ) -> None:
        self.model = model
        self.device = device
        self.meter = meter
        self.scratch_dir = Path(scratch_dir)
        self._audio_converter = None
        self._file_converter = None

    # -- public API ---------------------------------------------------------

    def estimate(self, audio: AudioBuffer) -> TempoEstimate:
        if audio.duration < 2.0:
            raise ValueError("audio must be at least 2 seconds long")

        beats_s, downbeats_s = self._predict(audio)
        beat_times = [float(value) * 1000.0 for value in beats_s]
        if len(beat_times) < 4:
            raise ValueError("Beat This! found too few beats")

        # The model emits beat frames on a coarse grid (~20 ms), so consecutive
        # differences alternate between neighbouring values and the median is
        # biased.  A least-squares fit over the whole beat list recovers the
        # true period.
        index = np.arange(len(beat_times), dtype=np.float64)
        slope, intercept = np.polyfit(index, np.asarray(beat_times), 1)
        if slope <= 0:
            raise ValueError("Beat This! produced a non-positive beat length")

        bpm = 60000.0 / float(slope)
        beat_ms = float(slope)
        offset_ms = float(intercept)
        fitted = intercept + index * slope
        residual = float(np.median(np.abs(np.asarray(beat_times) - fitted)))
        confidence = float(np.clip(1.0 - residual / (beat_ms * 0.5), 0.0, 1.0))

        downbeats = [float(value) * 1000.0 for value in downbeats_s]
        phase = self._downbeat_phase(beat_times, downbeats)

        count = int((audio.duration * 1000.0 - offset_ms) // beat_ms) + 1
        count = max(0, min(count, 100_000))
        beat_times_full = [offset_ms + position * beat_ms for position in range(count)]

        estimate = TempoEstimate(
            bpm=bpm,
            offset_ms=offset_ms,
            downbeat_phase=phase,
            confidence=confidence,
            residual_ms=residual,
            beat_times=beat_times_full,
            duration=audio.duration,
            source=self.name,
            meter=self.meter,
        )
        return estimate.normalized()

    # -- internals ----------------------------------------------------------

    def _predict(self, audio: AudioBuffer) -> tuple[np.ndarray, np.ndarray]:
        from beat_this.inference import Audio2Beats

        if self._audio_converter is None:
            self._audio_converter = Audio2Beats(
                checkpoint_path=self.model, device=self.device, dbn=False
            )
        try:
            beats, downbeats = self._audio_converter(audio.samples, audio.sample_rate)
        except TypeError:
            beats, downbeats = self._predict_from_file(audio)
        return np.asarray(beats), np.asarray(downbeats)

    def _predict_from_file(self, audio: AudioBuffer) -> tuple[np.ndarray, np.ndarray]:
        from beat_this.inference import File2Beats

        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        scratch = self.scratch_dir / f"beat-this-{uuid.uuid4().hex}.wav"
        try:
            pcm = np.clip(audio.samples, -1.0, 1.0)
            with wave.open(str(scratch), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(audio.sample_rate)
                out.writeframes((pcm * 32767.0).astype("<i2").tobytes())
            if self._file_converter is None:
                self._file_converter = File2Beats(
                    checkpoint_path=self.model, device=self.device, dbn=False
                )
            beats, downbeats = self._file_converter(str(scratch))
            return np.asarray(beats), np.asarray(downbeats)
        finally:
            scratch.unlink(missing_ok=True)

    def _downbeat_phase(
        self, beat_times_ms: list[float], downbeat_times_ms: list[float]
    ) -> int:
        if not downbeat_times_ms:
            return 0
        first = downbeat_times_ms[0]
        nearest = min(
            range(len(beat_times_ms)),
            key=lambda index: abs(beat_times_ms[index] - first),
        )
        return int(nearest % self.meter)
