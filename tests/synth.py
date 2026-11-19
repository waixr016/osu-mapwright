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


def _add(buffer: np.ndarray, start: int, sound: np.ndarray) -> None:
    if start < 0 or start >= len(buffer):
        return
    stop = min(start + len(sound), len(buffer))
    buffer[start:stop] += sound[: stop - start]


def structured_track(
    path: str | Path,
    *,
    bpm: float = 120.0,
    parts: tuple[tuple[int, float], ...] = ((8, 0.10), (8, 0.40), (8, 1.00), (8, 0.15)),
    sample_rate: int = 22050,
    seed: int = 5,
    bass_beats: tuple[int, ...] = (0, 1, 2, 3),
) -> Path:
    """Music with clear loudness steps, for section-segmentation tests.

    ``parts`` is a list of ``(bars, gain)`` pairs; the same groove is rendered
    throughout and each part is scaled afterwards, so the only cue the
    segmenter gets is energy.
    """
    rng = np.random.default_rng(seed)
    beat_s = 60.0 / bpm
    total_bars = sum(bars for bars, _ in parts)
    total = int((total_bars * 4 * beat_s + 0.5) * sample_rate)
    audio = np.zeros(total, dtype=np.float32)

    def at(beat: float) -> int:
        return int(round(beat * beat_s * sample_rate))

    def kick() -> np.ndarray:
        t = np.arange(int(0.16 * sample_rate)) / sample_rate
        freq = 110.0 * np.exp(-t * 26.0) + 42.0
        return (np.sin(2 * np.pi * freq * t) * np.exp(-t * 16.0) * 0.9).astype(np.float32)

    def snare() -> np.ndarray:
        t = np.arange(int(0.12 * sample_rate)) / sample_rate
        noise = rng.normal(0.0, 0.5, len(t)).astype(np.float32)
        tone = np.sin(2 * np.pi * 190.0 * t) * 0.35
        return ((noise + tone) * np.exp(-t * 34.0) * 0.7).astype(np.float32)

    def hat() -> np.ndarray:
        t = np.arange(int(0.04 * sample_rate)) / sample_rate
        noise = rng.normal(0.0, 0.4, len(t)).astype(np.float32)
        return (np.diff(noise, prepend=0.0) * np.exp(-t * 90.0) * 0.35).astype(np.float32)

    def tone(freq: float, length: float, amp: float) -> np.ndarray:
        t = np.arange(int(length * sample_rate)) / sample_rate
        envelope = np.minimum(1.0, t * 30.0) * np.exp(-t * 2.2)
        return (np.sin(2 * np.pi * freq * t) * envelope * amp).astype(np.float32)

    kick_sound, snare_sound, hat_sound = kick(), snare(), hat()
    progression = [55.0, 73.42, 65.41, 82.41]

    for bar in range(total_bars):
        root = progression[bar % len(progression)]
        base = bar * 4
        for beat_in_bar in range(4):
            beat = base + beat_in_bar
            _add(audio, at(beat), kick_sound if beat_in_bar in (0, 2) else snare_sound)
            _add(audio, at(beat), hat_sound * 0.6)
            _add(audio, at(beat + 0.5), hat_sound)
            if beat_in_bar in bass_beats:
                _add(audio, at(beat), tone(root, beat_s * 0.9, 0.5))
        for ratio in (2.0, 2.52, 3.0):
            _add(audio, at(base), tone(root * ratio, beat_s * 4.0, 0.16))

    # apply one gain per part so the sections differ only in loudness
    bar_cursor = 0
    for bars, gain in parts:
        first_sample = at(bar_cursor * 4)
        last_sample = at((bar_cursor + bars) * 4)
        audio[first_sample:last_sample] *= gain
        bar_cursor += bars

    peak = float(np.max(np.abs(audio))) or 1.0
    audio = (audio / peak * 0.9).astype(np.float32)

    target = Path(path)
    pcm = (audio * 32767.0).astype("<i2")
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return target


def music_track(
    path: str | Path,
    *,
    bpm: float = 128.0,
    bars: int = 16,
    sample_rate: int = 22050,
    offset_ms: float = 0.0,
    seed: int = 11,
) -> Path:
    """A more musical loop: kick/snare/hats, bass line and chord pads.

    Beat This! is trained on real music, so a bare click track is out of
    distribution; this gives the model something closer to what it expects.
    """
    rng = np.random.default_rng(seed)
    beat_s = 60.0 / bpm
    total = int((offset_ms / 1000.0 + bars * 4 * beat_s + 1.0) * sample_rate)
    audio = np.zeros(total, dtype=np.float32)

    def at(beat: float) -> int:
        return int(round((offset_ms / 1000.0 + beat * beat_s) * sample_rate))

    def kick() -> np.ndarray:
        t = np.arange(int(0.16 * sample_rate)) / sample_rate
        freq = 110.0 * np.exp(-t * 26.0) + 42.0
        return (np.sin(2 * np.pi * freq * t) * np.exp(-t * 16.0) * 0.9).astype(np.float32)

    def snare() -> np.ndarray:
        t = np.arange(int(0.12 * sample_rate)) / sample_rate
        noise = rng.normal(0.0, 0.5, len(t)).astype(np.float32)
        tone = np.sin(2 * np.pi * 190.0 * t) * 0.35
        return ((noise + tone) * np.exp(-t * 34.0) * 0.7).astype(np.float32)

    def hat() -> np.ndarray:
        t = np.arange(int(0.04 * sample_rate)) / sample_rate
        noise = rng.normal(0.0, 0.4, len(t)).astype(np.float32)
        bright = np.diff(noise, prepend=0.0)  # crude high pass
        return (bright * np.exp(-t * 90.0) * 0.35).astype(np.float32)

    def tone(freq: float, length: float, amp: float) -> np.ndarray:
        t = np.arange(int(length * sample_rate)) / sample_rate
        envelope = np.minimum(1.0, t * 30.0) * np.exp(-t * 2.2)
        return (np.sin(2 * np.pi * freq * t) * envelope * amp).astype(np.float32)

    kick_sound, snare_sound, hat_sound = kick(), snare(), hat()
    progression = [55.0, 73.42, 65.41, 82.41]  # A1, D2, C2, E2

    for bar in range(bars):
        root = progression[bar % len(progression)]
        base = bar * 4
        for beat_in_bar in range(4):
            beat = base + beat_in_bar
            if beat_in_bar in (0, 2):
                _add(audio, at(beat), kick_sound)
            else:
                _add(audio, at(beat), snare_sound)
            # eighth-note hats
            _add(audio, at(beat), hat_sound * 0.6)
            _add(audio, at(beat + 0.5), hat_sound)
            # bass on every beat
            _add(audio, at(beat), tone(root, beat_s * 0.9, 0.5))
        # sustained chord pad over the bar
        for ratio in (2.0, 2.52, 3.0):
            _add(audio, at(base), tone(root * ratio, beat_s * 4.0, 0.16))

    peak = float(np.max(np.abs(audio))) or 1.0
    audio = (audio / peak * 0.85).astype(np.float32)

    target = Path(path)
    pcm = (audio * 32767.0).astype("<i2")
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return target
