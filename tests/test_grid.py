"""Tests for the beat grid and red-line construction."""

from __future__ import annotations

import unittest

from mapwright.audio.base import TempoEstimate
from mapwright.osu.model import TimingPoint
from mapwright.timing import Grid, red_lines_from_estimate, validate


def red(time: int, bpm: float, meter: int = 4) -> TimingPoint:
    return TimingPoint.red(time, bpm, meter=meter)


class TestGridSingleTempo(unittest.TestCase):
    def setUp(self) -> None:
        # 120 BPM == 500 ms per beat, first beat at 1000 ms
        self.grid = Grid([red(1000, 120.0)])

    def test_beat_index(self) -> None:
        self.assertAlmostEqual(self.grid.beat_index(1000), 0.0)
        self.assertAlmostEqual(self.grid.beat_index(1500), 1.0)
        self.assertAlmostEqual(self.grid.beat_index(1750), 1.5)

    def test_time_at_beat(self) -> None:
        self.assertAlmostEqual(self.grid.time_at_beat(0), 1000.0)
        self.assertAlmostEqual(self.grid.time_at_beat(3), 2500.0)

    def test_ticks(self) -> None:
        ticks = self.grid.ticks(1000, 2000, 4)
        self.assertEqual(ticks, [1000, 1125, 1250, 1375, 1500, 1625, 1750, 1875, 2000])

    def test_ticks_respect_the_divisor(self) -> None:
        self.assertEqual(self.grid.ticks(1000, 2000, 1), [1000, 1500, 2000])
        self.assertEqual(self.grid.ticks(1000, 2000, 2), [1000, 1250, 1500, 1750, 2000])

    def test_snap(self) -> None:
        self.assertEqual(self.grid.snap(1037, 4), 1000)
        self.assertEqual(self.grid.snap(1140, 4), 1125)
        self.assertEqual(self.grid.snap(1240, 4), 1250)

    def test_is_snapped(self) -> None:
        self.assertTrue(self.grid.is_snapped(1250, 4))
        self.assertFalse(self.grid.is_snapped(1260, 4))

    def test_bar_start(self) -> None:
        self.assertEqual(self.grid.bar_start(1000), 1000)
        self.assertEqual(self.grid.bar_start(2600), 1000)
        self.assertEqual(self.grid.bar_start(3100), 3000)


class TestGridTempoChange(unittest.TestCase):
    def setUp(self) -> None:
        # 120 BPM until 10000 ms, then 150 BPM (400 ms per beat)
        self.grid = Grid([red(0, 120.0), red(10000, 150.0)])

    def test_beats_are_continuous_across_the_change(self) -> None:
        self.assertAlmostEqual(self.grid.beat_index(10000), 20.0)
        self.assertAlmostEqual(self.grid.beat_index(10400), 21.0)

    def test_time_at_beat_uses_the_second_section(self) -> None:
        self.assertAlmostEqual(self.grid.time_at_beat(21), 10400.0)

    def test_bpm_at(self) -> None:
        self.assertAlmostEqual(self.grid.bpm_at(5000), 120.0)
        self.assertAlmostEqual(self.grid.bpm_at(12000), 150.0)

    def test_ticks_cross_the_boundary(self) -> None:
        ticks = self.grid.ticks(9800, 10500, 1)
        self.assertEqual(ticks, [10000, 10400])

    def test_sections(self) -> None:
        from mapwright.timing import sections_from_grid

        sections = sections_from_grid(self.grid, 20000)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].start, 0)
        self.assertEqual(sections[0].end, 10000)
        self.assertAlmostEqual(sections[1].bpm, 150.0)


class TestGridValidation(unittest.TestCase):
    def test_empty_grid_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Grid([])

    def test_green_line_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Grid([TimingPoint.green(0, 1.0)])

    def test_invalid_divisor_is_rejected(self) -> None:
        grid = Grid([red(0, 120.0)])
        with self.assertRaises(ValueError):
            grid.ticks(0, 1000, 0)


class TestTempoEstimateNormalisation(unittest.TestCase):
    def test_negative_offset_shifts_whole_beats(self) -> None:
        estimate = TempoEstimate(bpm=120.0, offset_ms=-5.0, downbeat_phase=0, meter=4)
        normalised = estimate.normalized()
        self.assertAlmostEqual(normalised.offset_ms, 495.0)
        # beat 0 moved one beat later, so the downbeat is now the last beat
        self.assertEqual(normalised.downbeat_phase, 3)

    def test_positive_offset_is_left_alone(self) -> None:
        estimate = TempoEstimate(bpm=120.0, offset_ms=250.0, downbeat_phase=2)
        self.assertIs(estimate.normalized(), estimate)


class TestRedLinesFromEstimate(unittest.TestCase):
    def test_constant_tempo_produces_a_single_red_line(self) -> None:
        estimate = TempoEstimate(bpm=128.0, offset_ms=500.0)
        lines = red_lines_from_estimate(estimate)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].uninherited)
        self.assertAlmostEqual(lines[0].beat_length, 60000.0 / 128.0)
        self.assertEqual(lines[0].time, 500)

    def test_offset_is_preserved(self) -> None:
        estimate = TempoEstimate(bpm=120.0, offset_ms=3200.0)
        line = red_lines_from_estimate(estimate)[0]
        self.assertEqual(line.time, 3200)

    def test_negative_offset_is_normalised(self) -> None:
        estimate = TempoEstimate(bpm=120.0, offset_ms=-300.0)
        line = red_lines_from_estimate(estimate)[0]
        self.assertEqual(line.time, 200)

    def test_zero_bpm_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            red_lines_from_estimate(TempoEstimate(bpm=0.0, offset_ms=0.0))

    def test_validate_accepts_good_lines(self) -> None:
        estimate = TempoEstimate(bpm=174.0, offset_ms=120.0)
        self.assertEqual(validate(red_lines_from_estimate(estimate)), [])

    def test_validate_rejects_unsorted_lines(self) -> None:
        lines = [red(2000, 120.0), red(1000, 120.0)]
        self.assertIn("red lines are not strictly increasing in time", validate(lines))

    def test_validate_rejects_implausible_bpm(self) -> None:
        self.assertIn("implausible BPM", " ".join(validate([red(0, 5000.0)])))


if __name__ == "__main__":
    unittest.main()
