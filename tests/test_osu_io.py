"""Round-trip tests for the `.osu` reader/writer."""

from __future__ import annotations

import unittest
from pathlib import Path

from mapwright.osu import (
    Background,
    Beatmap,
    Break,
    Circle,
    Difficulty,
    General,
    HitSample,
    Metadata,
    Slider,
    Spinner,
    TimingPoint,
    fmt_num,
    parse,
    serialize,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestCanonicalRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (FIXTURES / "minimal.osu").read_text(encoding="utf-8")

    def test_serialize_reproduces_input_exactly(self) -> None:
        beatmap = parse(self.text)
        self.assertEqual(serialize(beatmap), self.text)

    def test_parse_is_idempotent(self) -> None:
        once = serialize(parse(self.text))
        twice = serialize(parse(once))
        self.assertEqual(once, twice)


class TestParsedValues(unittest.TestCase):
    def setUp(self) -> None:
        self.beatmap = parse((FIXTURES / "minimal.osu").read_text(encoding="utf-8"))

    def test_header(self) -> None:
        self.assertEqual(self.beatmap.format_version, 14)
        self.assertEqual(self.beatmap.general.audio_filename, "song.mp3")
        self.assertEqual(self.beatmap.general.mode, 0)
        self.assertAlmostEqual(self.beatmap.general.stack_leniency or 0, 0.7)

    def test_metadata(self) -> None:
        meta = self.beatmap.metadata
        self.assertEqual(meta.title, "Test Song")
        self.assertEqual(meta.creator, "mapwright")
        self.assertEqual(meta.version, "Normal")
        self.assertEqual(meta.beatmap_set_id, -1)

    def test_difficulty(self) -> None:
        diff = self.beatmap.difficulty
        self.assertAlmostEqual(diff.circle_size or 0, 4)
        self.assertAlmostEqual(diff.approach_rate or 0, 7)
        self.assertAlmostEqual(diff.slider_multiplier or 0, 1.4)

    def test_timing_points(self) -> None:
        points = self.beatmap.timing_points
        self.assertEqual(len(points), 2)
        red, green = points
        self.assertTrue(red.uninherited)
        self.assertAlmostEqual(red.bpm, 120.0)
        self.assertEqual(red.volume, 80)
        self.assertFalse(green.uninherited)
        self.assertAlmostEqual(green.sv, 2.0)
        self.assertTrue(green.kiai)

    def test_events(self) -> None:
        events = self.beatmap.events
        self.assertIsInstance(events[0], Background)
        self.assertEqual(events[0].filename, "bg.jpg")
        self.assertIsInstance(events[1], Break)
        self.assertEqual(events[1].end_time, 24000)

    def test_colours(self) -> None:
        self.assertEqual(self.beatmap.colours["Combo1"], (255, 0, 0))
        self.assertEqual(self.beatmap.colours["Combo2"], (0, 255, 0))

    def test_hit_objects(self) -> None:
        objects = self.beatmap.hit_objects
        self.assertEqual(len(objects), 5)

        first = objects[0]
        self.assertIsInstance(first, Circle)
        self.assertEqual(first.time, 1000)
        self.assertTrue(first.new_combo)
        self.assertEqual(first.type_bits, 5)

        slider = objects[3]
        self.assertIsInstance(slider, Slider)
        self.assertEqual(slider.curve_type, "B")
        self.assertEqual(slider.points, [(256, 100), (256, 100)])
        self.assertEqual(slider.slides, 1)
        self.assertAlmostEqual(slider.length, 140.0)
        self.assertEqual(slider.edge_sounds, [0, 0])
        self.assertEqual(slider.edge_sets, ["0:0", "0:0"])
        self.assertEqual(slider.type_bits, 6)

        spinner = objects[4]
        self.assertIsInstance(spinner, Spinner)
        self.assertEqual(spinner.end_time, 8000)
        self.assertEqual(spinner.type_bits, 12)

    def test_check_reports_no_problems(self) -> None:
        self.assertEqual(self.beatmap.check(), [])


class TestTimingHelpers(unittest.TestCase):
    def test_red_line_bpm_roundtrip(self) -> None:
        point = TimingPoint.red(1000, 180, meter=4, volume=70)
        self.assertAlmostEqual(point.beat_length, 60000 / 180)
        self.assertAlmostEqual(point.bpm, 180)
        self.assertEqual(point.render().split(",")[0], "1000")

    def test_green_line_sv_roundtrip(self) -> None:
        for sv in (0.5, 0.75, 1.0, 1.25, 2.0):
            point = TimingPoint.green(0, sv)
            self.assertAlmostEqual(point.sv, sv, places=6)
            self.assertLess(point.beat_length, 0)

    def test_beat_length_is_negative_for_green(self) -> None:
        self.assertEqual(TimingPoint.green(0, 2.0).beat_length, -50.0)


class TestNumberFormatting(unittest.TestCase):
    def test_integral_floats_lose_the_point(self) -> None:
        self.assertEqual(fmt_num(500.0), "500")
        self.assertEqual(fmt_num(1), "1")

    def test_repeating_decimals_are_truncated_to_six_places(self) -> None:
        self.assertEqual(fmt_num(60000 / 180), "333.333333")

    def test_small_decimals_keep_their_digits(self) -> None:
        self.assertEqual(fmt_num(0.7), "0.7")
        self.assertEqual(fmt_num(1.4), "1.4")


class TestLenientParsing(unittest.TestCase):
    def test_circle_without_sample(self) -> None:
        beatmap = parse("osu file format v14\n[HitObjects]\n256,192,1000,1,0\n")
        circle = beatmap.hit_objects[0]
        self.assertIsInstance(circle, Circle)
        self.assertEqual(circle.render(), "256,192,1000,1,0,0:0:0:0:")

    def test_slider_without_edge_fields(self) -> None:
        beatmap = parse(
            "osu file format v14\n[HitObjects]\n256,192,1000,2,0,L|300:200,1,100,0:0:0:0:\n"
        )
        slider = beatmap.hit_objects[0]
        self.assertIsInstance(slider, Slider)
        self.assertEqual(slider.edge_sounds, [])
        self.assertEqual(slider.edge_sets, [])

    def test_unknown_section_lines_are_preserved(self) -> None:
        text = (
            "osu file format v14\n"
            "[General]\n"
            "AudioFilename: a.mp3\n"
            "AudioHash: deadbeef\n"
            "OverlayPosition: Below\n"
            "FooBar: baz\n"
        )
        beatmap = parse(text)
        self.assertEqual(beatmap.general.audio_hash, "deadbeef")
        self.assertEqual(beatmap.general.overlay_position, "Below")
        rendered = serialize(beatmap)
        self.assertIn("AudioHash: deadbeef", rendered)
        self.assertIn("OverlayPosition: Below", rendered)
        self.assertIn("FooBar: baz", rendered)

    def test_unsorted_objects_are_reported(self) -> None:
        beatmap = parse(
            "osu file format v14\n"
            "[TimingPoints]\n0,500,4,1,0,100,1,0\n"
            "[HitObjects]\n256,192,2000,1,0,0:0:0:0:\n"
            "256,192,1000,1,0,0:0:0:0:\n"
        )
        self.assertIn("hit objects are not sorted by time", beatmap.check())

    def test_missing_red_line_is_reported(self) -> None:
        beatmap = parse(
            "osu file format v14\n"
            "[TimingPoints]\n0,-100,4,1,0,100,0,0\n"
        )
        self.assertIn("first timing point is not a red line", beatmap.check())


class TestProgrammaticBuild(unittest.TestCase):
    def _build(self) -> Beatmap:
        beatmap = Beatmap()
        beatmap.general = General(
            audio_filename="song.mp3",
            preview_time=1000,
            countdown=0,
            sample_set="Soft",
            stack_leniency=0.7,
            mode=0,
            letterbox_in_breaks=0,
            widescreen_storyboard=0,
        )
        beatmap.metadata = Metadata(
            title="Test Song",
            title_unicode="测试歌曲",
            artist="Test Artist",
            artist_unicode="测试歌手",
            creator="mapwright",
            version="Normal",
        )
        beatmap.difficulty = Difficulty(
            hp_drain_rate=5,
            circle_size=4,
            overall_difficulty=6,
            approach_rate=7,
            slider_multiplier=1.4,
            slider_tick_rate=1,
        )
        beatmap.timing_points = [TimingPoint.red(1000, 120, sample_set=1, volume=80)]
        beatmap.colours = {"Combo1": (255, 0, 0), "Combo2": (0, 128, 255)}
        beatmap.events = [Background("bg.jpg")]
        beatmap.hit_objects = [
            Circle(time=1000, x=256, y=192, new_combo=True),
            Circle(time=1500, x=128, y=192),
            Circle(time=2000, x=384, y=192),
            Slider(
                time=2500,
                x=256,
                y=192,
                new_combo=True,
                curve_type="L",
                points=[(396, 192)],
                slides=1,
                length=140.0,
                edge_sounds=[0, 0],
                edge_sets=["0:0", "0:0"],
            ),
            Spinner(time=4000, end_time=8000, new_combo=True, hitsound=4),
        ]
        return beatmap

    def test_build_serialize_parse(self) -> None:
        built = self._build()
        text = serialize(built)
        parsed = parse(text)

        self.assertEqual(len(parsed.hit_objects), 5)
        self.assertEqual(parsed.metadata.title_unicode, "测试歌曲")
        self.assertEqual(parsed.timing_points[0].volume, 80)
        self.assertEqual(parsed.hit_objects[3].length, 140.0)
        self.assertEqual(parsed.hit_objects[4].end_time, 8000)
        self.assertEqual(parsed.check(), [])

    def test_text_is_ascii_safe_outside_metadata(self) -> None:
        text = serialize(self._build())
        header = text.split("[Metadata]")[0]
        header.encode("ascii")  # raises if a stray non-ascii sneaks in


class TestHitSample(unittest.TestCase):
    def test_parse_and_render(self) -> None:
        sample = HitSample.parse("2:3:1:60:custom.wav")
        self.assertEqual(sample.normal_set, 2)
        self.assertEqual(sample.addition_set, 3)
        self.assertEqual(sample.index, 1)
        self.assertEqual(sample.volume, 60)
        self.assertEqual(sample.filename, "custom.wav")
        self.assertEqual(str(sample), "2:3:1:60:custom.wav")

    def test_unexpected_shape_is_preserved_verbatim(self) -> None:
        sample = HitSample.parse("0:0")
        self.assertIsNotNone(sample.raw)
        self.assertEqual(str(sample), "0:0")


if __name__ == "__main__":
    unittest.main()
