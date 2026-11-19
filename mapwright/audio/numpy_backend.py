"""Tempo estimation with nothing but numpy.

Pipeline: STFT → spectral-flux onset envelope → FFT autocorrelation for the
tempo → comb-filter phase search for the beat grid → circular-mean refinement
→ low-band accent matching for the downbeat.

It is not as accurate as a learned tracker on complex material, but it is
fast, deterministic and needs no model download.
"""

from __future__ import annotations

import math

import numpy as np

from .base import (
    ANALYSIS_SR,
    AudioBuffer,
    TempoEstimate,
    downbeat_phase,
)

N_FFT = 1024
HOP = 256


def _stft_magnitude(
    samples: np.ndarray, n_fft: int = N_FFT, hop: int = HOP, chunk: int = 512
) -> np.ndarray:
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


def _flux(magnitudes: np.ndarray) -> np.ndarray:
    compressed = np.log1p(magnitudes * 10.0)
    difference = np.diff(compressed, axis=0)
    flux = np.maximum(difference, 0.0).sum(axis=1)
    return np.concatenate([[0.0], flux]).astype(np.float32)


def _onset_envelope(magnitudes: np.ndarray) -> np.ndarray:
    flux = _flux(magnitudes)

    if len(flux) > 32:
        kernel = np.ones(32, dtype=np.float32) / 32.0
        flux = np.maximum(flux - np.convolve(flux, kernel, mode="same"), 0.0)
    return flux


def _autocorrelation(signal: np.ndarray) -> np.ndarray:
    size = len(signal)
    nfft = 1 << (2 * size - 1).bit_length()
    spectrum = np.fft.rfft(signal, nfft)
    power = np.fft.irfft(spectrum * np.conj(spectrum), nfft)[:size]
    return power


def _parabolic_peak(values: np.ndarray, index: int) -> float:
    if index <= 0 or index >= len(values) - 1:
        return float(index)
    left, middle, right = values[index - 1], values[index], values[index + 1]
    denominator = left - 2 * middle + right
    if abs(denominator) < 1e-12:
        return float(index)
    return float(index) + 0.5 * (left - right) / denominator


class NumpyTempoEstimator:
    """Pure-numpy beat tracker (default backend)."""

    name = "numpy"

    def __init__(
        self,
        min_bpm: float = 60.0,
        max_bpm: float = 240.0,
        preferred_bpm: float = 120.0,
        meter: int = 4,
        sample_rate: int = ANALYSIS_SR,
    ) -> None:
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self.preferred_bpm = preferred_bpm
        self.meter = meter
        self.sample_rate = sample_rate

    # -- public API ---------------------------------------------------------

    def estimate(self, audio: AudioBuffer) -> TempoEstimate:
        if audio.duration < 2.0:
            raise ValueError("audio must be at least 2 seconds long")

        analysed = audio.resample(self.sample_rate)
        fps = analysed.sample_rate / HOP
        pad_ms = (N_FFT // 2) * 1000.0 / analysed.sample_rate

        magnitudes = _stft_magnitude(analysed.samples)
        flux = _onset_envelope(magnitudes)
        if float(np.max(flux)) <= 0.0:
            raise ValueError("no onsets detected — is the track silent?")

        bpm, confidence = self._estimate_tempo(flux, fps)
        beat_ms = 60000.0 / bpm
        period = fps * beat_ms / 1000.0

        phase_frames, residual_frames = self._phase_offset(flux, fps, period)
        offset_ms = phase_frames / fps * 1000.0 - pad_ms
        offset_ms %= beat_ms
        offset_ms += self._whole_beats_to_first_onset(flux, fps, offset_ms, beat_ms, pad_ms)
        if offset_ms < 0:
            offset_ms += beat_ms * math.ceil(-offset_ms / beat_ms)

        beat_times = self._beat_times(offset_ms, beat_ms, analysed.duration)

        low_bin = max(1, int(150.0 * N_FFT / analysed.sample_rate))
        low_flux = _flux(magnitudes[:, :low_bin])
        phase_in_bar = downbeat_phase(low_flux, fps, beat_times, self.meter)

        return TempoEstimate(
            bpm=float(bpm),
            offset_ms=float(offset_ms),
            downbeat_phase=phase_in_bar,
            confidence=confidence,
            residual_ms=residual_frames / fps * 1000.0,
            beat_times=beat_times,
            duration=audio.duration,
            source=self.name,
        )

    # -- internals ----------------------------------------------------------

    def _estimate_tempo(self, flux: np.ndarray, fps: float) -> tuple[float, float]:
        signal = flux - flux.mean()
        acf = _autocorrelation(signal)
        lags = np.arange(len(acf))
        counts = np.maximum(len(signal) - lags, 1)
        acf = acf / counts

        min_lag = max(2, int(np.floor(fps * 60.0 / self.max_bpm)))
        max_lag = min(len(acf) - 1, int(np.ceil(fps * 60.0 / self.min_bpm)))
        if max_lag <= min_lag + 2:
            raise ValueError("audio is too short to estimate tempo")

        segment = acf[min_lag:max_lag]
        candidates = fps * 60.0 / np.arange(min_lag, max_lag)
        prior = np.exp(-0.5 * (np.log2(candidates / self.preferred_bpm) / 0.9) ** 2)
        scores = segment * prior

        best = int(np.argmax(scores))
        refined_lag = min_lag + _parabolic_peak(scores, best)
        bpm = fps * 60.0 / refined_lag

        baseline = float(np.median(np.abs(segment))) or 1e-9
        confidence = float(np.clip((segment[best] / baseline) / 8.0, 0.0, 1.0))
        return float(bpm), confidence

    def _phase_offset(
        self, flux: np.ndarray, fps: float, period: float
    ) -> tuple[float, float]:
        """Beat phase (frames) and its circular spread (frames)."""
        best_phase, best_score = 0.0, -1.0
        for phase in np.arange(0.0, period, 0.5):
            indices = np.arange(phase, len(flux), period).astype(int)
            indices = indices[indices < len(flux)]
            if len(indices) < 4:
                continue
            score = float(flux[indices].mean())
            if score > best_score:
                best_phase, best_score = float(phase), score

        weights = flux.astype(np.float64)
        total = float(weights.sum())
        if total <= 0.0:
            return best_phase, 0.0

        frames = np.arange(len(flux), dtype=np.float64)
        angles = 2.0 * np.pi * (frames - best_phase) / period
        vector = np.sum(weights * np.exp(1j * angles))
        magnitude = float(np.abs(vector)) / total
        delta = float(np.angle(vector)) / (2.0 * np.pi) * period
        spread = math.sqrt(max(0.0, -2.0 * math.log(max(magnitude, 1e-12))))
        spread *= period / (2.0 * np.pi)
        return best_phase + delta, spread

    def _whole_beats_to_first_onset(
        self,
        flux: np.ndarray,
        fps: float,
        offset_ms: float,
        beat_ms: float,
        pad_ms: float,
    ) -> float:
        """Shift the offset forward whole beats so beat 0 is the first onset."""
        threshold = 0.3 * float(np.max(flux))
        above = np.flatnonzero(flux > threshold)
        if len(above) == 0:
            return 0.0
        first_onset_ms = float(above[0]) / fps * 1000.0 - pad_ms
        if first_onset_ms <= offset_ms:
            return 0.0
        beats = math.ceil((first_onset_ms - offset_ms) / beat_ms - 1e-9)
        return beats * beat_ms

    def _beat_times(self, offset_ms: float, beat_ms: float, duration: float) -> list[float]:
        if beat_ms <= 0:
            return []
        count = int((duration * 1000.0 - offset_ms) // beat_ms) + 1
        count = max(0, min(count, 100_000))
        return [offset_ms + index * beat_ms for index in range(count)]
