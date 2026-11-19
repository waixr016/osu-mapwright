"""Synthetic audio helpers for the tests (click tracks, accents, silence)."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def click_track(
    path: str | Path,
    *,
    bpm: float = 128.0,
    duration_s: float = 20.0,
    sample_rate: int = 22050,
    offset_ms: float = 500.0,
    accent_every: int = 4,
    accent_phase: int = 0,
    noise_level: float = 0.002,
    seed: int = 7,
) -> Path:
    """Write a WAV file of clicks with a louder low-frequency accent every bar."""
    rng = np.random.default_rng(seed)
    total = int(duration_s * sample_rate)
    audio = rng.normal(0.0, noise_level, total).astype(np.float32)

    beat_ms = 60000.0 / bpm
    click_len = int(0.03 * sample_rate)
    click_t = np.arange(click_len) / sample_rate
    click = (np.sin(2 * np.pi * 2000.0 * click_t) * np.exp(-click_t * 180.0)).astype(
        np.float32
    )

    accent_len = int(0.12 * sample_rate)
    accent_t = np.arange(accent_len) / sample_rate
    accent = (
        np.sin(2 * np.pi * 60.0 * accent_t) * np.exp(-accent_t * 22.0) * 1.6
    ).astype(np.float32)

    index = 0
    while True:
        time_ms = offset_ms + index * beat_ms
        if time_ms >= duration_s * 1000.0:
            break
        start = int(round(time_ms / 1000.0 * sample_rate))
        if 0 <= start < total:
            stop = min(start + click_len, total)
            audio[start:stop] += click[: stop - start]
            if index % accent_every == accent_phase:
                stop = min(start + accent_len, total)
                audio[start:stop] += accent[: stop - start]
        index += 1

    peak = float(np.max(np.abs(audio))) or 1.0
    audio = (audio / peak * 0.8).astype(np.float32)

    target = Path(path)
    pcm = (audio * 32767.0).astype("<i2")
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return target


def silence(path: str | Path, *, duration_s: float = 5.0, sample_rate: int = 22050) -> Path:
    target = Path(path)
    frames = np.zeros(int(duration_s * sample_rate), dtype="<i2")
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames.tobytes())
    return target
