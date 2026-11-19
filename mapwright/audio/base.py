"""Audio decoding and the tempo-estimator interface.

The interface is deliberately small so backends are interchangeable::

    from mapwright.audio import load_audio, get_estimator

    audio = load_audio("song.mp3")
    estimate = get_estimator().estimate(audio)

Backends return a :class:`TempoEstimate`; everything downstream (grid, red
lines) only depends on that dataclass.
"""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

import numpy as np

#: analysis rate used by the numpy backend and for beat refinement
ANALYSIS_SR = 22050


@dataclass
class AudioBuffer:
    """Mono float32 samples plus their sample rate."""

    sample_rate: int
    samples: np.ndarray

    def __post_init__(self) -> None:
        if self.samples.ndim != 1:
            raise ValueError("AudioBuffer expects mono samples")
        if self.samples.dtype != np.float32:
            self.samples = self.samples.astype(np.float32)

    @property
    def duration(self) -> float:
        return len(self.samples) / float(self.sample_rate)

    def resample(self, target_rate: int) -> "AudioBuffer":
        """Cheap linear resampling — good enough for onset analysis."""
        if target_rate == self.sample_rate:
            return self
        ratio = target_rate / float(self.sample_rate)
        new_length = int(round(len(self.samples) * ratio))
        if new_length <= 1:
            raise ValueError("audio is too short to resample")
        source = np.linspace(0.0, len(self.samples) - 1, new_length)
        indices = np.arange(new_length) / ratio
        indices = np.clip(indices, 0, len(self.samples) - 1)
        resampled = np.interp(indices, np.arange(len(self.samples)), self.samples)
        del source
        return AudioBuffer(int(target_rate), resampled.astype(np.float32))


@dataclass
class TempoEstimate:
    """What every backend must produce."""

    bpm: float
    offset_ms: float
    #: 0-3, which beat of the bar carries the downbeat
    downbeat_phase: int = 0
    confidence: float = 1.0
    #: mean absolute distance between detected onsets and the fitted grid
    residual_ms: float = 0.0
    beat_times: list[float] = field(default_factory=list)
    duration: float = 0.0
    source: str = "unknown"
    meter: int = 4

    @property
    def beat_length(self) -> float:
        return 60000.0 / self.bpm

    def beat_at(self, index: int) -> float:
        """Time (ms) of beat ``index`` counting from the first beat."""
        return self.offset_ms + index * self.beat_length

    def normalized(self, min_offset_ms: float = 0.0) -> "TempoEstimate":
        """Return a copy whose offset is at least ``min_offset_ms``.

        Shifting the grid by whole beats keeps every beat where it was, so the
        downbeat phase is rotated by the same amount and stays meaningful.
        """
        if self.offset_ms >= min_offset_ms - 1e-9:
            return self
        beat = self.beat_length
        beats = math.ceil((min_offset_ms - self.offset_ms) / beat)
        shift = beats * beat
        return replace(
            self,
            offset_ms=self.offset_ms + shift,
            downbeat_phase=(self.downbeat_phase - beats) % self.meter,
            beat_times=[time + shift for time in self.beat_times],
        )

    def summary(self) -> str:
        return (
            f"{self.bpm:.2f} BPM, offset {self.offset_ms:.0f} ms, "
            f"downbeat {self.downbeat_phase}, residual {self.residual_ms:.1f} ms, "
            f"confidence {self.confidence:.2f} [{self.source}]"
        )


@runtime_checkable
class TempoEstimator(Protocol):
    """Anything that can turn audio into a :class:`TempoEstimate`."""

    name: str

    def estimate(self, audio: AudioBuffer) -> TempoEstimate: ...


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------


def _load_wav(path: Path) -> AudioBuffer:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported WAV sample width: {width} bytes")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return AudioBuffer(rate, data.astype(np.float32))


def load_audio(path: str | Path) -> AudioBuffer:
    """Decode an audio file to mono float32.

    Uses ``soundfile`` when available (mp3/ogg/flac), and falls back to the
    standard library for plain WAV so the test suite needs no extra packages.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        import soundfile  # type: ignore[import-not-found]
    except ImportError:
        if path.suffix.lower() != ".wav":
            raise RuntimeError(
                f"cannot decode {path.suffix} without the 'soundfile' package"
            ) from None
        return _load_wav(path)

    data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    return AudioBuffer(int(rate), data.mean(axis=1).astype(np.float32))


# ---------------------------------------------------------------------------
# shared signal helpers
# ---------------------------------------------------------------------------


def downbeat_phase(
    accent: np.ndarray,
    frames_per_second: float,
    beat_times_ms: Sequence[float],
    meter: int = 4,
) -> int:
    """Pick which beat of the bar carries the strongest low-frequency accent.

    ``accent`` is a per-frame onset envelope computed on low frequencies only
    (kick drums and bass), sampled at ``frames_per_second``.
    """
    if len(beat_times_ms) < meter or frames_per_second <= 0:
        return 0
    scores = []
    for phase in range(meter):
        values = []
        for index, time_ms in enumerate(beat_times_ms):
            if index % meter != phase:
                continue
            position = int(round(time_ms / 1000.0 * frames_per_second))
            if 0 <= position < len(accent):
                values.append(float(accent[position]))
        scores.append(float(np.mean(values)) if values else 0.0)
    return int(np.argmax(scores))


def get_estimator(name: str = "auto", **kwargs) -> TempoEstimator:
    """Return a tempo estimator by name.

    ``"auto"`` prefers Beat This!, then librosa, then the numpy backend.
    Backends are imported lazily so a missing optional dependency only costs
    the fallback, not an error. Extra keyword arguments go to the backend
    constructor (e.g. ``model="final0"`` or ``device="cuda"``).
    """
    if name == "numpy":
        from .numpy_backend import NumpyTempoEstimator

        return NumpyTempoEstimator(**kwargs)  # type: ignore[return-value]
    if name == "librosa":
        from .librosa_backend import LibrosaTempoEstimator

        return LibrosaTempoEstimator(**kwargs)  # type: ignore[return-value]
    if name == "beat_this":
        from .beat_this_backend import BeatThisEstimator

        return BeatThisEstimator(**kwargs)  # type: ignore[return-value]
    if name != "auto":
        raise ValueError(f"unknown backend: {name!r}")

    try:
        from .beat_this_backend import BeatThisEstimator

        return BeatThisEstimator(**kwargs)  # type: ignore[return-value]
    except ImportError:
        pass
    try:
        from .librosa_backend import LibrosaTempoEstimator

        return LibrosaTempoEstimator(**kwargs)  # type: ignore[return-value]
    except ImportError:
        pass

    from .numpy_backend import NumpyTempoEstimator

    return NumpyTempoEstimator()  # type: ignore[return-value]
