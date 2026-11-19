"""osu! standard beatmap I/O.

>>> from mapwright.osu import parse, serialize
>>> beatmap = parse(open("song.osu", encoding="utf-8").read())
>>> text = serialize(beatmap)
"""

from __future__ import annotations

from pathlib import Path

from .model import (
    PLAYFIELD_CENTER,
    PLAYFIELD_HEIGHT,
    PLAYFIELD_WIDTH,
    Background,
    Beatmap,
    Break,
    Circle,
    Difficulty,
    Editor,
    General,
    HitObject,
    HitSample,
    HitSound,
    Metadata,
    ObjectType,
    RawEvent,
    Slider,
    Spinner,
    TimingPoint,
    Video,
    fmt_num,
)
from .reader import parse, parse_file
from .writer import serialize

__all__ = [
    "PLAYFIELD_CENTER",
    "PLAYFIELD_HEIGHT",
    "PLAYFIELD_WIDTH",
    "Background",
    "Beatmap",
    "Break",
    "Circle",
    "Difficulty",
    "Editor",
    "General",
    "HitObject",
    "HitSample",
    "HitSound",
    "Metadata",
    "ObjectType",
    "RawEvent",
    "Slider",
    "Spinner",
    "TimingPoint",
    "Video",
    "fmt_num",
    "load",
    "parse",
    "parse_file",
    "save",
    "serialize",
]


def load(path: str | Path) -> Beatmap:
    """Read a `.osu` file from disk."""
    return parse_file(path)


def save(beatmap: Beatmap, path: str | Path) -> Path:
    """Write ``beatmap`` to ``path`` as UTF-8 without a BOM, ``\\n`` endings."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(serialize(beatmap))
    return target
