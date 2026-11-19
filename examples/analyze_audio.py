"""Analyse an audio file and, optionally, write a timing-skeleton beatmap.

Usage::

    python examples/analyze_audio.py song.mp3
    python examples/analyze_audio.py song.mp3 --skeleton -o build

The skeleton map has one circle per beat, which is the fastest way to eyeball
whether the timing is right: open it in the editor, watch the playfield, and
the circles should land on the beat.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapwright.audio import get_estimator, load_audio  # noqa: E402
from mapwright.osu import (  # noqa: E402
    Beatmap,
    Circle,
    Difficulty,
    General,
    Metadata,
    save,
)
from mapwright.timing import red_lines_from_estimate, validate  # noqa: E402

SKELETON_BEATS = 64


def build_skeleton(estimate, red_lines, audio_path: Path) -> Beatmap:
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
        version="Timing",
    )
    beatmap.difficulty = Difficulty(
        hp_drain_rate=5,
        circle_size=4,
        overall_difficulty=5,
        approach_rate=7,
        slider_multiplier=1.4,
        slider_tick_rate=1,
    )
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("build"))
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "beat_this", "numpy", "librosa"],
    )
    parser.add_argument("--meter", type=int, default=4)
    parser.add_argument("--skeleton", action="store_true", help="write a 1/1 test map")
    args = parser.parse_args(argv)

    audio = load_audio(args.audio)
    estimator = get_estimator(args.backend)
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
