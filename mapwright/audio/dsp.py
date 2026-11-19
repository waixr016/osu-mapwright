"""Small DSP primitives shared by the audio backends and the salience stage.

Everything here is numpy-only and operates on mono float32 samples.
"""

from __future__ import annotations

import numpy as np

DEFAULT_N_FFT = 1024
DEFAULT_HOP = 256


def stft_magnitude(
    samples: np.ndarray,
    n_fft: int = DEFAULT_N_FFT,
    hop: int = DEFAULT_HOP,
    chunk: int = 512,
) -> np.ndarray:
    """Magnitude spectrogram, ``(frames, n_fft // 2 + 1)``.

    The signal is zero-padded by ``n_fft // 2`` on both sides, so frame ``k``
    is centred on sample ``k * hop``; use :func:`frame_times_ms` to convert.
    """
    pad = n_fft // 2
    padded = np.pad(samples, (pad, pad), mode="reflect")
    n_frames = 1 + (len(padded) - n_fft) // hop
    window = np.hanning(n_fft).astype(np.float32)
    magnitudes = np.empty((n_frames, n_fft // 2 + 1), dtype=np.float32)
    offsets = np.arange(n_fft)
    for start in range(0, n_frames, chunk):
        stop = min(start + chunk, n_frames)
        indices = np.arange(start, stop)[:, None] * hop + offsets[None, :]
        magnitudes[start:stop] = np.abs(np.fft.rfft(padded[indices] * window, axis=1))
    return magnitudes


def flux(magnitudes: np.ndarray) -> np.ndarray:
    """Positive log-spectral difference summed over bins."""
    compressed = np.log1p(magnitudes * 10.0)
    difference = np.diff(compressed, axis=0)
    values = np.maximum(difference, 0.0).sum(axis=1)
    return np.concatenate([[0.0], values]).astype(np.float32)


def frame_times_ms(
    n_frames: int, hop: int, sample_rate: int, n_fft: int = DEFAULT_N_FFT
) -> np.ndarray:
    """Centre time of every STFT frame, in milliseconds.

    ``stft_magnitude`` pads by ``n_fft // 2``, so the centre of frame ``k``
    sits at ``(k * hop - n_fft / 2) / sr``; forgetting the padding shifts the
    whole curve earlier by ~23 ms at 22 kHz.
    """
    indices = np.arange(n_frames, dtype=np.float64)
    return (indices * hop - n_fft / 2.0) * 1000.0 / sample_rate


def robust_normalise(values: np.ndarray, low: float = 10.0, high: float = 90.0) -> np.ndarray:
    """Scale to 0..1 using percentiles so a few loud hits do not dominate."""
    if len(values) == 0:
        return values
    low_value, high_value = np.percentile(values, low), np.percentile(values, high)
    if high_value - low_value <= 1e-9:
        return np.zeros_like(values, dtype=np.float64)
    return np.clip((values - low_value) / (high_value - low_value), 0.0, 1.0)
