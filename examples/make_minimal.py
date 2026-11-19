"""Write a small but genuinely playable osu! standard beatmap.

Run from the repository root::

    python examples/make_minimal.py

Then drop any ``song.mp3`` next to the generated ``.osu`` file, copy the folder
into your osu! ``Songs`` directory and press ``F5`` in the song select screen.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapwright.osu import (  # noqa: E402
    Background,
    Beatmap,
    Break,
    Circle,
    Difficulty,
    General,
    HitSample,
    HitSound,
    Metadata,
    Slider,
    Spinner,
    TimingPoint,
    save,
    serialize,
)

BPM = 120.0
OFFSET = 1000
BEAT_MS = 60000.0 / BPM  # 500 ms


def beat(count: float) -> int:
    """Millisecond timestamp ``count`` beats after the first beat."""
    return int(round(OFFSET + count * BEAT_MS))


def build() -> Beatmap:
    beatmap = Beatmap()
    beatmap.general = General(
        audio_filename="song.mp3",
        audio_lead_in=0,
        preview_time=beat(4),
        countdown=0,
        sample_set="Soft",
        stack_leniency=0.7,
        mode=0,
        letterbox_in_breaks=0,
        widescreen_storyboard=0,
    )
    beatmap.metadata = Metadata(
        title="Minimal Test",
        title_unicode="Minimal Test",
        artist="mapwright",
        artist_unicode="mapwright",
        creator="mapwright",
        version="Normal",
        tags="mapwright test",
    )
    beatmap.difficulty = Difficulty(
        hp_drain_rate=5,
        circle_size=4,
        overall_difficulty=6,
        approach_rate=7,
        slider_multiplier=1.4,
        slider_tick_rate=1,
    )
    beatmap.events = [Background("bg.jpg"), Break(beat(20), beat(22))]
    beatmap.colours = {
        "Combo1": (255, 96, 96),
        "Combo2": (96, 160, 255),
        "Combo3": (255, 220, 96),
    }

    # one red line is enough for a constant-tempo song
    beatmap.timing_points = [TimingPoint.red(OFFSET, BPM, sample_set=2, volume=70)]

    objects = []
    # 4 bars of 1/1 circles, moving around the playfield with distance snap
    # roughly at 140 px per beat (SliderMultiplier 1.4 * 100 * 1.0)
    objects.append(Circle(time=beat(0), x=256, y=192, new_combo=True))
    objects.append(Circle(time=beat(1), x=396, y=192, hitsound=HitSound.WHISTLE))
    objects.append(Circle(time=beat(2), x=396, y=332))
    objects.append(Circle(time=beat(3), x=256, y=332, hitsound=HitSound.CLAP))
    objects.append(Circle(time=beat(4), x=116, y=332, new_combo=True))
    objects.append(Circle(time=beat(5), x=116, y=192))
    objects.append(Circle(time=beat(6), x=256, y=52, hitsound=HitSound.FINISH))

    # a 1-beat slider: 140 px long at 120 BPM with SM 1.4 == exactly one beat
    objects.append(
        Slider(
            time=beat(8),
            x=256,
            y=192,
            new_combo=True,
            curve_type="L",
            points=[(396, 192)],
            slides=1,
            length=140.0,
            edge_sounds=[0, 0],
            edge_sets=["0:0", "0:0"],
            hit_sample=HitSample(normal_set=2, addition_set=2, volume=70),
        )
    )
    # reversing slider covering two beats
    objects.append(
        Slider(
            time=beat(10),
            x=256,
            y=192,
            curve_type="L",
            points=[(256, 52)],
            slides=2,
            length=140.0,
            edge_sounds=[0, 0, 0],
            edge_sets=["0:0", "0:0", "0:0"],
        )
    )

    objects.append(Circle(time=beat(13), x=256, y=52, new_combo=True))
    objects.append(Circle(time=beat(14), x=256, y=192, hitsound=HitSound.WHISTLE))
    objects.append(Spinner(time=beat(16), end_time=beat(20), new_combo=True, hitsound=4))

    beatmap.hit_objects = objects
    return beatmap


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build")
    beatmap = build()

    problems = beatmap.check()
    if problems:
        print("refusing to write, structural problems:", *problems, sep="\n  ")
        return 1

    name = f"{beatmap.metadata.artist} - {beatmap.metadata.title} "
    name += f"({beatmap.metadata.creator}) [{beatmap.metadata.version}].osu"
    path = save(beatmap, output_dir / name)

    print(f"wrote {path}")
    print(f"  objects: {len(beatmap.hit_objects)}")
    print(f"  timing points: {len(beatmap.timing_points)}")
    print(f"  bytes: {len(serialize(beatmap))}")
    print()
    print("next: put a song.mp3 and bg.jpg next to it, then F5 in osu!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
