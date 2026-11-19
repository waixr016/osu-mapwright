"""Tests for tempo estimation on synthetic click tracks."""

from __future__ import annotations

import unittest
from pathlib import Path

from mapwright.audio import NumpyTempoEstimator, get_estimator, load_audio
from tests.synth import click_track, music_track, silence

#: Scratch files live inside the repo: the sandbox denies the system temp
#: directory, and ``tempfile.mkdtemp`` creates a DACL that the runner cannot
#: write into, so plain ``mkdir`` it is.
TMP_ROOT = Path(__file__).resolve().parents[1] / "build" / "test-tmp"


class TestNumpyTempoEstimator(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = TMP_ROOT / self.id().rsplit(".", 1)[-1]
        self.dir.mkdir(parents=True, exist_ok=True)
        for stale in self.dir.glob("*"):
            stale.unlink()
        self.estimator = NumpyTempoEstimator()

    def tearDown(self) -> None:
        for stale in self.dir.glob("*"):
            stale.unlink()
        self.dir.rmdir()

    def _estimate(self, **kwargs):
        path = click_track(self.dir / "click.wav", **kwargs)
        return self.estimator.estimate(load_audio(path))

    def test_bpm_and_offset_of_a_128_track(self) -> None:
        estimate = self._estimate(bpm=128.0, offset_ms=500.0)
        self.assertAlmostEqual(estimate.bpm, 128.0, delta=2.0)
        self.assertLess(abs(estimate.offset_ms - 500.0), 30.0)
        self.assertGreater(estimate.confidence, 0.0)

    def test_offset_lands_on_the_first_beat(self) -> None:
        estimate = self._estimate(bpm=120.0, offset_ms=1400.0)
        self.assertLess(abs(estimate.offset_ms - 1400.0), 30.0)

    def test_downbeat_phase_with_accent_on_the_first_beat(self) -> None:
        estimate = self._estimate(bpm=128.0, accent_phase=0, duration_s=24.0)
        self.assertEqual(estimate.downbeat_phase, 0)

    def test_downbeat_phase_with_accent_on_the_third_beat(self) -> None:
        estimate = self._estimate(bpm=128.0, accent_phase=2, duration_s=24.0)
        self.assertEqual(estimate.downbeat_phase, 2)

    def test_beat_times_follow_the_estimated_grid(self) -> None:
        estimate = self._estimate(bpm=128.0, offset_ms=500.0)
        self.assertGreater(len(estimate.beat_times), 20)
        gap = estimate.beat_times[1] - estimate.beat_times[0]
        self.assertAlmostEqual(gap, estimate.beat_length, delta=0.5)

    def test_summary_is_human_readable(self) -> None:
        estimate = self._estimate(bpm=128.0)
        text = estimate.summary()
        self.assertIn("BPM", text)
        self.assertIn("offset", text)

    def test_silence_is_rejected(self) -> None:
        path = silence(self.dir / "silence.wav")
        with self.assertRaises(ValueError):
            self.estimator.estimate(load_audio(path))

    def test_too_short_audio_is_rejected(self) -> None:
        path = click_track(self.dir / "short.wav", duration_s=1.0)
        with self.assertRaises(ValueError):
            self.estimator.estimate(load_audio(path))


class TestEstimatorSelection(unittest.TestCase):
    def test_auto_returns_a_working_estimator(self) -> None:
        estimator = get_estimator()
        self.assertTrue(hasattr(estimator, "estimate"))
        self.assertIn(estimator.name, {"numpy", "librosa", "beat_this"})

    def test_numpy_backend_can_be_requested_explicitly(self) -> None:
        self.assertEqual(get_estimator("numpy").name, "numpy")

    def test_unknown_backend_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            get_estimator("nope")


def _beat_this_available() -> bool:
    try:
        import beat_this  # noqa: F401
    except Exception:  # noqa: BLE001 - torch can fail in creative ways
        return False
    return True


@unittest.skipUnless(_beat_this_available(), "beat_this is not installed")
class TestAutoPrefersBeatThis(unittest.TestCase):
    def test_auto_selects_beat_this(self) -> None:
        self.assertEqual(get_estimator("auto").name, "beat_this")

    def test_beat_this_is_selectable_explicitly(self) -> None:
        self.assertEqual(get_estimator("beat_this").name, "beat_this")


@unittest.skipUnless(_beat_this_available(), "beat_this is not installed")
class TestBeatThisAccuracy(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = TMP_ROOT / self.id().rsplit(".", 1)[-1]
        self.dir.mkdir(parents=True, exist_ok=True)
        for stale in self.dir.glob("*"):
            stale.unlink()

    def tearDown(self) -> None:
        for stale in self.dir.glob("*"):
            stale.unlink()
        self.dir.rmdir()

    def test_musical_loop(self) -> None:
        path = music_track(self.dir / "music.wav", bpm=128.0, bars=8)
        try:
            estimate = get_estimator("beat_this").estimate(load_audio(path))
        except Exception as error:  # noqa: BLE001 - missing checkpoint, no GPU...
            self.skipTest(f"Beat This! unavailable here: {error}")

        self.assertAlmostEqual(estimate.bpm, 128.0, delta=1.0)
        self.assertEqual(estimate.source, "beat_this")
        self.assertLess(estimate.residual_ms, 40.0)
        self.assertLess(estimate.offset_ms, estimate.beat_length + 40.0)

        # the loop starts on a downbeat, so time 0 must be a downbeat beat
        index_of_zero = round((0.0 - estimate.offset_ms) / estimate.beat_length)
        self.assertEqual(index_of_zero % 4, estimate.downbeat_phase)


if __name__ == "__main__":
    unittest.main()
