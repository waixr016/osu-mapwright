"""Analyse an audio file and, optionally, write a skeleton or rhythm beatmap.

Usage::

    python examples/analyze_audio.py song.mp3
    python examples/analyze_audio.py song.mp3 --structure
    python examples/analyze_audio.py song.mp3 --skeleton -o build
    python examples/analyze_audio.py song.mp3 --rhythm -o build

``--skeleton`` writes one circle per beat, which is the fastest way to eyeball
whether the timing is right. ``--rhythm`` runs the section analysis and the
rhythm generator, and writes the resulting note times as circles on a fixed
ring so the rhythm can be heard in the editor. Geometry comes in S5.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapwright.audio import get_estimator, load_audio  # noqa: E402
from mapwright.audio.onsets import SalienceExtractor  # noqa: E402
from mapwright.osu import (  # noqa: E402
    Beatmap,
    Circle,
    Difficulty,
    General,
    Metadata,
    save,
)
from mapwright.rhythm import (  # noqa: E402
    AccentTemplate,
    RhythmConfig,
    generate_rhythm,
    rhythm_statistics,
)
from mapwright.structure import MusicSection, SectionMap, segment  # noqa: E402
from mapwright.timing import Grid, red_lines_from_estimate, validate  # noqa: E402

SKELETON_BEATS = 64

#: placeholder geometry for the rhythm preview: a 140 px ring
RING = ((256, 192), (396, 192), (396, 332), (116, 332))


def _blank_beatmap(audio_path: Path, version: str) -> Beatmap:
    beatmap = Beatmap()
    beatmap.general = General(
        audio_filename=audio_path.name,
        sample_set="Soft",
        mode=0,
    )
    beatmap.metadata = Metadata(
        title=audio_path.stem,
        title_unicode=audio_path.stem,
        artist="unknown",
        artist_unicode="unknown",
        creator="mapwright",
        version=version,
    )
    beatmap.difficulty = Difficulty(
        hp_drain_rate=5,
        circle_size=4,
        overall_difficulty=5,
        approach_rate=7,
        slider_multiplier=1.4,
        slider_tick_rate=1,
    )
    return beatmap


def build_skeleton(estimate, red_lines, audio_path: Path) -> Beatmap:
    beatmap = _blank_beatmap(audio_path, "Timing")
    beatmap.timing_points = red_lines

    objects: list[Circle] = []
    for index in range(SKELETON_BEATS):
        time = int(round(estimate.offset_ms + index * estimate.beat_length))
        if time > estimate.duration * 1000:
            break
        objects.append(
            Circle(
                time=time,
                x=256,
                y=192,
                # start a combo on every downbeat so the skeleton shows bars
                new_combo=(index - estimate.downbeat_phase) % 4 == 0,
            )
        )
    beatmap.hit_objects = objects
    return beatmap


def build_rhythm(red_lines, events, audio_path: Path) -> Beatmap:
    beatmap = _blank_beatmap(audio_path, "Rhythm")
    beatmap.timing_points = red_lines
    beatmap.colours = {"Combo1": (255, 96, 96), "Combo2": (96, 160, 255)}

    objects: list[Circle] = []
    for index, event in enumerate(events):
        x, y = RING[index % len(RING)]
        objects.append(
            Circle(
                time=event.time,
                x=x,
                y=y,
                new_combo=index == 0 or event.position == 0,
            )
        )
    beatmap.hit_objects = objects
    return beatmap


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("build"))
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "beat_this", "numpy", "librosa"],
    )
    parser.add_argument(
        "--model",
        default="final0",
        help="Beat This! checkpoint (final0 is the most accurate, ~81 MB)",
    )
    parser.add_argument("--device", default="cpu", help="torch device, e.g. cuda")
    parser.add_argument("--meter", type=int, default=4)
    parser.add_argument("--divisor", type=int, default=4, help="rhythm grid, 4 = 1/4")
    parser.add_argument("--skeleton", action="store_true", help="write a 1/1 test map")
    parser.add_argument("--structure", action="store_true", help="print the section table")
    parser.add_argument("--rhythm", action="store_true", help="write a rhythm-only map")
    args = parser.parse_args(argv)

    audio = load_audio(args.audio)
    kwargs = {}
    if args.backend in ("auto", "beat_this"):
        kwargs = {"model": args.model, "device": args.device}
    estimator = get_estimator(args.backend, **kwargs)
    print(f"decoding      {args.audio.name}  ({audio.duration:.1f}s @ {audio.sample_rate} Hz)")
    print(f"backend       {estimator.name}")

    estimate = estimator.estimate(audio)
    print(f"tempo         {estimate.bpm:.2f} BPM  (beat {estimate.beat_length:.2f} ms)")
    print(f"offset        {estimate.offset_ms:.1f} ms")
    print(f"downbeat      beat {estimate.downbeat_phase} of the bar")
    print(f"residual      {estimate.residual_ms:.1f} ms")
    print(f"confidence    {estimate.confidence:.2f}")

    red_lines = red_lines_from_estimate(estimate, meter=args.meter)
    problems = validate(red_lines)
    if problems:
        print("timing warnings:")
        for problem in problems:
            print(f"  - {problem}")

    grid = Grid([point for point in red_lines if point.uninherited])
    sections: list[MusicSection] = []
    section_map: SectionMap | None = None
    if args.structure or args.rhythm:
        sections = segment(audio, grid)
        section_map = SectionMap(sections)

    if args.structure and section_map is not None:
        print()
        print("sections:")
        print(section_map.table())
        print(
            f"kiai {section_map.kiai_duration / 1000:.1f}s "
            f"of {section_map.duration / 1000:.1f}s"
        )

    if args.rhythm and section_map is not None:
        salience = SalienceExtractor(audio).curves
        accent = AccentTemplate.build(
            salience, grid, phase=estimate.downbeat_phase, meter=args.meter
        )
        events = generate_rhythm(
            sections,
            grid,
            salience,
            accent,
            phase=estimate.downbeat_phase,
            config=RhythmConfig(divisor=args.divisor),
        )
        stats = rhythm_statistics(events, int(audio.duration * 1000))
        print()
        print(f"accent        {accent.summary()}")
        print(
            f"rhythm        {int(stats['notes'])} notes, {stats['nps']:.2f} NPS, "
            f"{stats['on_beat_ratio'] * 100:.0f}% on beat"
        )
        beatmap = build_rhythm(red_lines, events, args.audio)
        path = save(beatmap, args.output / f"unknown - {args.audio.stem} (mapwright) [Rhythm].osu")
        print(f"rhythm map    {path}")
        print("copy it next to the audio file and press F5 in osu!")
        return 0

    if not args.skeleton:
        return 0

    beatmap = build_skeleton(estimate, red_lines, args.audio)
    name = f"unknown - {args.audio.stem} (mapwright) [Timing].osu"
    path = save(beatmap, args.output / name)
    print()
    print(f"skeleton map  {path}  ({len(beatmap.hit_objects)} circles)")
    print("copy it next to the audio file and press F5 in osu!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
