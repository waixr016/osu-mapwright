"""Serialise a :class:`~mapwright.osu.model.Beatmap` back into `.osu` text."""

from __future__ import annotations

from .model import (
    Background,
    Beatmap,
    Break,
    Difficulty,
    Editor,
    General,
    HitObject,
    Metadata,
    RawEvent,
    Video,
)

_FORMAT_LINE = "osu file format v{version}"


def _kv_section(title: str, rows: list[tuple[str, str]], extras: list[str], *, space: bool) -> list[str]:
    lines = [f"[{title}]"]
    separator = ": " if space else ":"
    for key, value in rows:
        lines.append(f"{key}{separator}{value}")
    lines.extend(extras)
    return lines


def serialize(beatmap: Beatmap) -> str:
    """Render ``beatmap`` as `.osu` text (UTF-8, ``\\n`` line endings)."""
    blocks: list[list[str]] = []

    blocks.append([_FORMAT_LINE.format(version=beatmap.format_version)])

    blocks.append(
        _kv_section(
            "General",
            beatmap.general.items(),
            beatmap.extras.get("General", []),
            space=True,
        )
    )
    blocks.append(
        _kv_section(
            "Editor",
            beatmap.editor.items(),
            beatmap.extras.get("Editor", []),
            space=True,
        )
    )
    blocks.append(
        _kv_section(
            "Metadata",
            beatmap.metadata.items(),
            beatmap.extras.get("Metadata", []),
            space=False,
        )
    )
    blocks.append(
        _kv_section(
            "Difficulty",
            beatmap.difficulty.items(),
            beatmap.extras.get("Difficulty", []),
            space=False,
        )
    )

    event_lines = ["[Events]"]
    event_lines.extend(item.render() for item in beatmap.events)
    event_lines.extend(beatmap.extras.get("Events", []))
    blocks.append(event_lines)

    timing_lines = ["[TimingPoints]"]
    timing_lines.extend(point.render() for point in beatmap.timing_points)
    timing_lines.extend(beatmap.extras.get("TimingPoints", []))
    blocks.append(timing_lines)

    colour_lines = ["[Colours]"]
    for name, rgb in beatmap.colours.items():
        colour_lines.append(f"{name} : {rgb[0]},{rgb[1]},{rgb[2]}")
    colour_lines.extend(beatmap.extras.get("Colours", []))
    blocks.append(colour_lines)

    object_lines = ["[HitObjects]"]
    object_lines.extend(hit_object.render() for hit_object in beatmap.hit_objects)
    object_lines.extend(beatmap.extras.get("HitObjects", []))
    blocks.append(object_lines)

    out: list[str] = []
    for block in blocks:
        out.extend(block)
        out.append("")
    return "\n".join(out)
