"""Parse `.osu` text into a :class:`~mapwright.osu.model.Beatmap`."""

from __future__ import annotations

import re
from pathlib import Path

from .model import (
    Background,
    Beatmap,
    Break,
    Circle,
    HitObject,
    HitSample,
    RawEvent,
    Slider,
    Spinner,
    TimingPoint,
    Video,
)

_FORMAT_RE = re.compile(r"^osu file format v(\d+)\s*$")
_INT_RE = re.compile(r"^-?\d+$")
_EDGE_SET_RE = re.compile(r"^\d+:\d+$")


def _split_key_value(line: str) -> tuple[str, str] | None:
    index = line.find(":")
    if index < 0:
        return None
    return line[:index].strip(), line[index + 1 :].strip()


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _looks_like_edge_sounds(value: str) -> bool:
    parts = value.split("|")
    return bool(parts) and all(_INT_RE.match(part.strip()) for part in parts if part.strip() != "")


def _looks_like_edge_sets(value: str) -> bool:
    parts = value.split("|")
    return bool(parts) and all(_EDGE_SET_RE.match(part.strip()) for part in parts)


def _parse_timing_point(line: str) -> TimingPoint | None:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 2:
        return None
    try:
        time = int(round(float(parts[0])))
        beat_length = float(parts[1])
    except ValueError:
        return None

    def field(index: int, default: int) -> int:
        if index >= len(parts) or parts[index] == "":
            return default
        try:
            return int(parts[index])
        except ValueError:
            return default

    return TimingPoint(
        time=time,
        beat_length=beat_length,
        meter=field(2, 4),
        sample_set=field(3, 0),
        sample_index=field(4, 0),
        volume=field(5, 100),
        uninherited=field(6, 1) != 0,
        effects=field(7, 0),
    )


def _parse_hit_object(line: str) -> HitObject | None:
    parts = line.split(",")
    if len(parts) < 5:
        return None
    try:
        x = int(parts[0])
        y = int(parts[1])
        time = int(parts[2])
        type_bits = int(parts[3])
        hit_sound = int(parts[4])
    except ValueError:
        return None

    new_combo = bool(type_bits & 4)
    combo_skip = (type_bits >> 4) & 0b111
    rest = parts[5:]

    if type_bits & 128:
        # osu!mania hold notes are out of scope; keep the raw line intact
        return RawEvent(line)

    if type_bits & 8:
        end_time = 0
        if rest:
            try:
                end_time = int(rest[0])
            except ValueError:
                end_time = 0
        sample = HitSample.parse(rest[1]) if len(rest) > 1 else HitSample()
        return Spinner(
            time=time,
            end_time=end_time,
            new_combo=new_combo,
            combo_skip=combo_skip,
            hitsound=hit_sound,
            hit_sample=sample,
        )

    if type_bits & 2:
        return _parse_slider(x, y, time, hit_sound, new_combo, combo_skip, rest)

    sample = HitSample.parse(rest[0]) if rest else HitSample()
    return Circle(
        time=time,
        x=x,
        y=y,
        new_combo=new_combo,
        combo_skip=combo_skip,
        hitsound=hit_sound,
        hit_sample=sample,
    )


def _parse_slider(
    x: int,
    y: int,
    time: int,
    hit_sound: int,
    new_combo: bool,
    combo_skip: int,
    rest: list[str],
) -> HitObject | None:
    if len(rest) < 3:
        return None
    curve_string = rest[0]
    try:
        slides = int(rest[1])
        length = float(rest[2])
    except ValueError:
        return None

    curve_type = "B"
    points: list[tuple[int, int]] = []
    raw_points: str | None = None
    curve_parts = curve_string.split("|")
    if curve_parts and curve_parts[0]:
        curve_type = curve_parts[0]
    for point in curve_parts[1:]:
        coordinate = point.split(":")
        if len(coordinate) != 2:
            raw_points = curve_string
            points = []
            break
        try:
            points.append((int(coordinate[0]), int(coordinate[1])))
        except ValueError:
            raw_points = curve_string
            points = []
            break

    tail = rest[3:]
    index = 0
    edge_sounds: list[int] = []
    edge_sets: list[str] = []
    if index < len(tail) and _looks_like_edge_sounds(tail[index]):
        edge_sounds = [int(v) for v in tail[index].split("|") if v.strip() != ""]
        index += 1
    if index < len(tail) and _looks_like_edge_sets(tail[index]):
        edge_sets = [v for v in tail[index].split("|") if v.strip() != ""]
        index += 1
    sample = HitSample.parse(tail[index]) if index < len(tail) else HitSample()

    return Slider(
        time=time,
        x=x,
        y=y,
        new_combo=new_combo,
        combo_skip=combo_skip,
        hitsound=hit_sound,
        hit_sample=sample,
        curve_type=curve_type,
        points=points,
        raw_points=raw_points,
        slides=slides,
        length=length,
        edge_sounds=edge_sounds,
        edge_sets=edge_sets,
    )


def _parse_event(line: str) -> object:
    parts = line.split(",")
    kind = parts[0].strip() if parts else ""
    if kind in ("0", "Background") and len(parts) >= 3:
        return Background(
            filename=_unquote(parts[2]),
            x=int(parts[3]) if len(parts) > 3 and _INT_RE.match(parts[3].strip()) else 0,
            y=int(parts[4]) if len(parts) > 4 and _INT_RE.match(parts[4].strip()) else 0,
        )
    if kind in ("Video", "1") and len(parts) >= 3:
        try:
            start_time = int(parts[1])
        except ValueError:
            return RawEvent(line)
        return Video(start_time=start_time, filename=_unquote(parts[2]))
    if kind in ("2", "Break") and len(parts) >= 3:
        try:
            return Break(start_time=int(parts[1]), end_time=int(parts[2]))
        except ValueError:
            return RawEvent(line)
    return RawEvent(line)


def _parse_colour(line: str) -> tuple[str, tuple[int, int, int]] | None:
    split = _split_key_value(line)
    if split is None:
        return None
    key, value = split
    try:
        channels = [int(channel.strip()) for channel in value.split(",")[:3]]
    except ValueError:
        return None
    if len(channels) != 3:
        return None
    return key, (channels[0], channels[1], channels[2])


def parse(text: str) -> Beatmap:
    """Parse `.osu` text. Unknown keys are preserved in ``beatmap.extras``."""
    beatmap = Beatmap()
    section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        match = _FORMAT_RE.match(line)
        if match:
            beatmap.format_version = int(match.group(1))
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue

        if section == "General":
            split = _split_key_value(line)
            if split and beatmap.general.set(*split):
                continue
        elif section == "Editor":
            split = _split_key_value(line)
            if split and beatmap.editor.set(*split):
                continue
        elif section == "Metadata":
            split = _split_key_value(line)
            if split and beatmap.metadata.set(*split):
                continue
        elif section == "Difficulty":
            split = _split_key_value(line)
            if split and beatmap.difficulty.set(*split):
                continue
        elif section == "Events":
            beatmap.events.append(_parse_event(line))
            continue
        elif section == "TimingPoints":
            point = _parse_timing_point(line)
            if point is not None:
                beatmap.timing_points.append(point)
                continue
        elif section == "Colours":
            colour = _parse_colour(line)
            if colour is not None:
                beatmap.colours[colour[0]] = colour[1]
                continue
        elif section == "HitObjects":
            hit_object = _parse_hit_object(line)
            if hit_object is not None:
                beatmap.hit_objects.append(hit_object)
                continue

        beatmap.extras.setdefault(section or "_preamble", []).append(line)

    return beatmap


def parse_file(path: str | Path) -> Beatmap:
    """Read and parse a `.osu` file (tolerates a UTF-8 BOM)."""
    return parse(Path(path).read_text(encoding="utf-8-sig"))
