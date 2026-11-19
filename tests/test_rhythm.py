"""Tests for onset salience, accent learning and rhythm selection."""

from __future__ import annotations

import unittest
from pathlib import Path

from mapwright.audio.base import load_audio
from mapwright.audio.onsets import SalienceExtractor
from mapwright.osu.model import TimingPoint
from mapwright.rhythm import AccentTemplate, RhythmConfig, generate_rhythm, rhythm_statistics
from mapwright.structure import MusicSection, segment
from mapwright.timing.grid import Grid
from tests.synth import structured_track

TMP_ROOT = Path(__file__).resolve().parents[1] / "build" / "test-tmp"

BPM = 120.0
BEAT_MS = 500
BAR_MS = 2000


class _RhythmCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = TMP_ROOT / cls.__name__
        cls.dir.mkdir(parents=True, exist_ok=True)
        # one steady groove: kick on 1/3, snare on 2/4, hats on every 8th,
        # bass doubling the kick so the low band is not busy on every beat
        cls.audio = load_audio(
            structured_track(
                cls.dir / "groove.wav", bpm=BPM, parts=((16, 1.0),), bass_beats=(0, 2)
            )
        )
        cls.grid = Grid([TimingPoint.red(0, BPM)])
        cls.salience = SalienceExtractor(cls.audio).curves
        cls.accent = AccentTemplate.build(cls.salience, cls.grid, phase=0, meter=4)

    @classmethod
    def tearDownClass(cls) -> None:
        for stale in cls.dir.glob("*"):
            stale.unlink()
        cls.dir.rmdir()


class TestSalience(_RhythmCase):
    def test_curve_covers_the_track(self) -> None:
        self.assertGreater(len(self.salience), 10)
        self.assertAlmostEqual(self.salience.times_ms[-1], 32000, delta=500)

    def test_downbeat_is_louder_than_the_gap_between_beats(self) -> None:
        downbeat = sum(self.salience.at(4000).values())
        offbeat = sum(self.salience.at(4250).values())
        self.assertGreater(downbeat, offbeat)

    def test_salience_is_normalised(self) -> None:
        for band, values in self.salience.bands.items():
            self.assertLessEqual(float(values.max()), 1.0 + 1e-6, band)
            self.assertGreaterEqual(float(values.min()), 0.0, band)


class TestAccentTemplate(_RhythmCase):
    def test_template_has_one_weight_per_position(self) -> None:
        self.assertEqual(len(self.accent.weights), 8)
        self.assertAlmostEqual(max(self.accent.weights.values()), 1.0)

    def test_kick_positions_dominate_the_low_band(self) -> None:
        low = self.accent.band_weights["low"]
        self.assertGreater(low[0], low[2])
        self.assertGreater(low[4], low[6])

    def test_snare_positions_dominate_the_mid_band(self) -> None:
        mid = self.accent.band_weights["mid"]
        self.assertGreater(mid[2], mid[0])
        self.assertGreater(mid[6], mid[4])

    def test_weight_lookup_wraps(self) -> None:
        self.assertAlmostEqual(self.accent.weight(8), self.accent.weight(0))
        self.assertAlmostEqual(self.accent.weight(-1), self.accent.weight(7))


class TestRhythmGeneration(_RhythmCase):
    def _sections(self) -> list[MusicSection]:
        return segment(self.audio, self.grid)

    def test_events_are_snapped_to_the_grid(self) -> None:
        sections = self._sections()
        events = generate_rhythm(sections, self.grid, self.salience, self.accent)
        self.assertTrue(events)
        for event in events:
            self.assertAlmostEqual(self.grid.beat_index(event.time) * 4 % 1, 0.0, places=6)

    def test_events_are_sorted_and_unique(self) -> None:
        sections = self._sections()
        events = generate_rhythm(sections, self.grid, self.salience, self.accent)
        times = [event.time for event in events]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))

    def test_density_respects_the_cap(self) -> None:
        sections = self._sections()
        config = RhythmConfig(max_nps=3.0)
        events = generate_rhythm(
            sections, self.grid, self.salience, self.accent, config=config
        )
        stats = rhythm_statistics(events, int(self.audio.duration * 1000))
        self.assertLessEqual(stats["nps"], 3.0 + 1e-6)

    def test_density_follows_the_section(self) -> None:
        sections = [
            MusicSection(start=0, end=16_000, role="verse", energy=0.2, density=1.0),
            MusicSection(start=16_000, end=32_000, role="chorus", energy=1.0, density=4.0),
        ]
        events = generate_rhythm(sections, self.grid, self.salience, self.accent)
        first = [e for e in events if e.time < 16_000]
        second = [e for e in events if e.time >= 16_000]
        self.assertGreater(len(second), len(first))

    def test_most_notes_land_on_beats(self) -> None:
        sections = self._sections()
        events = generate_rhythm(sections, self.grid, self.salience, self.accent)
        stats = rhythm_statistics(events, int(self.audio.duration * 1000))
        self.assertGreater(stats["on_beat_ratio"], 0.8)

    def test_sparse_sections_anchor_on_downbeats(self) -> None:
        sections = [
            MusicSection(start=0, end=32_000, role="intro", energy=0.1, density=0.5)
        ]
        events = generate_rhythm(sections, self.grid, self.salience, self.accent)
        self.assertTrue(events)
        on_downbeat = sum(1 for event in events if event.position == 0)
        self.assertGreater(on_downbeat / len(events), 0.5)

    def test_metrical_prior_can_be_disabled(self) -> None:
        config = RhythmConfig(downbeat_prior=1.0, beat_prior=1.0, offbeat_prior=1.0)
        self.assertEqual(config.metrical_prior(0), 1.0)
        self.assertEqual(config.metrical_prior(1), 1.0)
        default = RhythmConfig()
        self.assertGreater(default.metrical_prior(0), default.metrical_prior(2))
        self.assertGreater(default.metrical_prior(2), default.metrical_prior(1))

    def test_empty_sections_produce_nothing(self) -> None:
        self.assertEqual(
            generate_rhythm([], self.grid, self.salience, self.accent), []
        )


class TestRhythmConfig(unittest.TestCase):
    def test_invalid_divisor_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RhythmConfig(divisor=0)

    def test_invalid_subdivision_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RhythmConfig(subdivision=0)

    def test_band_weights_default(self) -> None:
        self.assertIn("low", RhythmConfig().band_weights)


if __name__ == "__main__":
    unittest.main()
