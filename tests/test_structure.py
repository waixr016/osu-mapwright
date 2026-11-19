"""Tests for section segmentation and the density curve."""

from __future__ import annotations

import unittest
from pathlib import Path

from mapwright.audio.base import load_audio
from mapwright.osu.model import TimingPoint
from mapwright.structure import (
    DensityProfile,
    SectionMap,
    bar_features,
    bar_spans,
    detect_boundaries,
    segment,
)
from mapwright.timing.grid import Grid
from tests.synth import structured_track

TMP_ROOT = Path(__file__).resolve().parents[1] / "build" / "test-tmp"

#: 120 BPM, 4/4 -> one bar is exactly 2000 ms
BPM = 120.0
BAR_MS = 2000

#: quiet intro, verse, loud chorus, quiet outro
PARTS = ((8, 0.10), (8, 0.40), (8, 1.00), (8, 0.15))


class _SectionCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = TMP_ROOT / cls.__name__
        cls.dir.mkdir(parents=True, exist_ok=True)
        cls.audio = load_audio(structured_track(cls.dir / "structured.wav", bpm=BPM, parts=PARTS))
        cls.grid = Grid([TimingPoint.red(0, BPM)])
        cls.sections = segment(cls.audio, cls.grid)

    @classmethod
    def tearDownClass(cls) -> None:
        for stale in cls.dir.glob("*"):
            stale.unlink()
        cls.dir.rmdir()


class TestBarGrid(_SectionCase):
    def test_bars_are_two_seconds(self) -> None:
        spans = bar_spans(self.grid, 8000)
        self.assertEqual(len(spans), 4)
        self.assertEqual(spans[0], (0, 2000))
        self.assertEqual(spans[3], (6000, 8000))

    def test_bar_features_cover_the_track(self) -> None:
        features = bar_features(self.audio, self.grid)
        self.assertEqual(len(features), sum(bars for bars, _ in PARTS))
        self.assertAlmostEqual(features[0].loudness, 0.0, delta=0.5)


class TestBoundaries(_SectionCase):
    def test_detected_cuts_land_near_the_part_changes(self) -> None:
        features = bar_features(self.audio, self.grid)
        cuts = detect_boundaries(features)
        expected = [0, 8, 16, 24]
        for target in expected[1:]:
            self.assertTrue(
                any(abs(cut - target) <= 2 for cut in cuts),
                f"no cut near bar {target}, got {cuts}",
            )

    def test_number_of_sections_is_reasonable(self) -> None:
        self.assertGreaterEqual(len(self.sections), 3)
        self.assertLessEqual(len(self.sections), 8)


class TestRolesAndDensity(_SectionCase):
    def test_loud_part_is_the_chorus(self) -> None:
        chorus = [s for s in self.sections if s.role == "chorus"]
        self.assertTrue(chorus)
        # the loud part is bars 16..24, i.e. 32 s .. 48 s
        middle = (32_000 + 48_000) / 2
        self.assertTrue(any(s.start <= middle <= s.end for s in chorus))

    def test_density_follows_energy(self) -> None:
        intro = min(self.sections, key=lambda s: s.start)
        chorus = max(self.sections, key=lambda s: s.energy)
        self.assertLess(intro.density, chorus.density)

    def test_density_is_within_the_profile(self) -> None:
        profile = DensityProfile(min_nps=0.5, max_nps=6.0)
        for section in self.sections:
            self.assertGreaterEqual(section.density, profile.min_nps - 1e-9)
            self.assertLessEqual(section.density, profile.max_nps + 1e-9)

    def test_kiai_is_limited_and_on_the_chorus(self) -> None:
        kiai = [s for s in self.sections if s.kiai]
        self.assertTrue(kiai)
        self.assertTrue(all(s.role == "chorus" for s in kiai))

    def test_sections_tile_the_track_without_gaps(self) -> None:
        for previous, current in zip(self.sections, self.sections[1:]):
            self.assertEqual(previous.end, current.start)
        self.assertEqual(self.sections[0].start, 0)

    def test_sv_stays_in_a_sane_range(self) -> None:
        for section in self.sections:
            self.assertGreaterEqual(section.sv, 0.8)
            self.assertLessEqual(section.sv, 1.25)


class TestDensityProfile(unittest.TestCase):
    def test_curve_is_monotonic(self) -> None:
        profile = DensityProfile(min_nps=1.0, max_nps=5.0)
        values = [profile.density_for(energy / 10) for energy in range(11)]
        self.assertEqual(values, sorted(values))

    def test_curve_hits_both_ends(self) -> None:
        profile = DensityProfile(min_nps=1.0, max_nps=5.0)
        self.assertAlmostEqual(profile.density_for(0.0), 1.0)
        self.assertAlmostEqual(profile.density_for(1.0), 5.0)

    def test_invalid_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DensityProfile(min_nps=2.0, max_nps=1.0)


class TestSectionMap(_SectionCase):
    def test_lookup_returns_the_section(self) -> None:
        section_map = SectionMap(self.sections)
        section = section_map.section_at(10_000)
        self.assertIsNotNone(section)
        self.assertTrue(section.start <= 10_000 < section.end)

    def test_density_is_eased_at_boundaries(self) -> None:
        section_map = SectionMap(self.sections, transition_ms=1000)
        first, second = self.sections[0], self.sections[1]
        just_after = section_map.density_at(second.start + 50)
        middle = section_map.density_at(second.start + 5000)
        self.assertAlmostEqual(middle, second.density, places=6)
        self.assertNotAlmostEqual(just_after, second.density, places=3)
        self.assertLess(just_after, max(first.density, second.density) + 1e-9)

    def test_table_is_renderable(self) -> None:
        table = SectionMap(self.sections).table()
        self.assertIn("chorus", table)
        self.assertIn("nps=", table)


if __name__ == "__main__":
    unittest.main()
