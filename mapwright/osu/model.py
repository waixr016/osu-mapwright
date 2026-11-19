"""osu! standard beatmap data model.

The model mirrors the `.osu` file format closely enough that a map can be
read, modified and written back without losing information.  Fields that are
optional in the format are ``None`` when absent so that serialisation never
invents values that were not there.

See <https://osu.ppy.sh/wiki/en/Client/File_formats/osu_%28file_format%29>.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag
from typing import ClassVar, Optional

PLAYFIELD_WIDTH = 512
PLAYFIELD_HEIGHT = 384
PLAYFIELD_CENTER = (256, 192)

SAMPLE_SETS = {"normal": 1, "soft": 2, "drum": 3}


# ---------------------------------------------------------------------------
# bit flags
# ---------------------------------------------------------------------------


class ObjectType(IntFlag):
    """Bit flags stored in the ``type`` column of a hit object."""

    CIRCLE = 1
    SLIDER = 2
    NEW_COMBO = 4
    SPINNER = 8
    MANIA_HOLD = 128

    COMBO_SKIP_SHIFT = 4
    COMBO_SKIP_MASK = 0b111 << COMBO_SKIP_SHIFT


class HitSound(IntFlag):
    """Bit flags stored in the ``hitSound`` column of a hit object."""

    NORMAL = 1
    WHISTLE = 2
    FINISH = 4
    CLAP = 8


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def fmt_num(value: float | int) -> str:
    """Format a number the way osu! does: no trailing zeros, dot decimal."""
    if isinstance(value, bool):  # guard against accidental bools
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if value == int(value):
        return str(int(value))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass
class HitSample:
    """The ``normalSet:additionSet:index:volume:filename`` tail of an object."""

    normal_set: int = 0
    addition_set: int = 0
    index: int = 0
    volume: int = 0
    filename: str = ""
    #: set when the original text did not fit the expected shape; wins on write
    raw: Optional[str] = None

    def __str__(self) -> str:
        if self.raw is not None:
            return self.raw
        return (
            f"{self.normal_set}:{self.addition_set}:{self.index}:"
            f"{self.volume}:{self.filename}"
        )

    @classmethod
    def parse(cls, text: str) -> "HitSample":
        text = text.strip()
        parts = text.split(":")
        if len(parts) != 5:
            return cls(raw=text)
        try:
            return cls(
                normal_set=int(parts[0]),
                addition_set=int(parts[1]),
                index=int(parts[2]),
                volume=int(parts[3]),
                filename=parts[4],
            )
        except ValueError:
            return cls(raw=text)


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# hit objects
# ---------------------------------------------------------------------------


@dataclass
class HitObject:
    """Common part of every hit object."""

    time: int
    x: int = PLAYFIELD_CENTER[0]
    y: int = PLAYFIELD_CENTER[1]
    new_combo: bool = False
    combo_skip: int = 0
    hitsound: HitSound = HitSound(0)
    hit_sample: HitSample = field(default_factory=HitSample)

    kind: ClassVar[str] = "object"
    base_type: ClassVar[ObjectType] = ObjectType(0)

    @property
    def type_bits(self) -> int:
        bits = int(self.base_type)
        if self.new_combo:
            bits |= int(ObjectType.NEW_COMBO)
        bits |= (self.combo_skip & 0b111) << int(ObjectType.COMBO_SKIP_SHIFT)
        return bits

    def head(self) -> str:
        return (
            f"{self.x},{self.y},{self.time},"
            f"{self.type_bits},{int(self.hitsound)}"
        )

    def params(self) -> list[str]:
        """Type specific columns that follow ``hitSound``."""
        return []

    def render(self) -> str:
        columns = [self.head(), *self.params(), str(self.hit_sample)]
        return ",".join(columns)


@dataclass
class Circle(HitObject):
    kind: ClassVar[str] = "circle"
    base_type: ClassVar[ObjectType] = ObjectType.CIRCLE


@dataclass
class Slider(HitObject):
    kind: ClassVar[str] = "slider"
    base_type: ClassVar[ObjectType] = ObjectType.SLIDER

    curve_type: str = "B"
    points: list[tuple[int, int]] = field(default_factory=list)
    slides: int = 1
    length: float = 0.0
    edge_sounds: list[int] = field(default_factory=list)
    edge_sets: list[str] = field(default_factory=list)
    #: preserved verbatim when the file contained something unexpected
    raw_points: Optional[str] = None

    def curve_string(self) -> str:
        if self.raw_points is not None:
            return self.raw_points
        anchors = "|".join(f"{x}:{y}" for x, y in self.points)
        return f"{self.curve_type}|{anchors}" if anchors else self.curve_type

    def params(self) -> list[str]:
        columns = [self.curve_string(), str(self.slides), fmt_num(self.length)]
        if self.edge_sounds or self.edge_sets:
            columns.append("|".join(str(s) for s in self.edge_sounds))
            columns.append("|".join(self.edge_sets))
        return columns


@dataclass
class Spinner(HitObject):
    kind: ClassVar[str] = "spinner"
    base_type: ClassVar[ObjectType] = ObjectType.SPINNER

    end_time: int = 0

    def __post_init__(self) -> None:
        # spinners ignore their position; normalise it like the editor does
        self.x, self.y = PLAYFIELD_CENTER

    def params(self) -> list[str]:
        return [str(self.end_time)]


# ---------------------------------------------------------------------------
# timing
# ---------------------------------------------------------------------------


@dataclass
class TimingPoint:
    """A red (uninherited) or green (inherited) timing point."""

    time: int
    beat_length: float
    meter: int = 4
    sample_set: int = 0
    sample_index: int = 0
    volume: int = 100
    uninherited: bool = True
    effects: int = 0

    # -- constructors -------------------------------------------------------

    @classmethod
    def red(
        cls,
        time: int,
        bpm: float,
        *,
        meter: int = 4,
        sample_set: int = 0,
        volume: int = 100,
        kiai: bool = False,
    ) -> "TimingPoint":
        if bpm <= 0:
            raise ValueError("bpm must be positive")
        return cls(
            time=time,
            beat_length=60000.0 / bpm,
            meter=meter,
            sample_set=sample_set,
            volume=volume,
            uninherited=True,
            effects=1 if kiai else 0,
        )

    @classmethod
    def green(
        cls,
        time: int,
        sv: float = 1.0,
        *,
        volume: int = 100,
        sample_set: int = 0,
        kiai: bool = False,
    ) -> "TimingPoint":
        if sv <= 0:
            raise ValueError("sv must be positive")
        return cls(
            time=time,
            beat_length=-100.0 / sv,
            sample_set=sample_set,
            volume=volume,
            uninherited=False,
            effects=1 if kiai else 0,
        )

    # -- derived values -----------------------------------------------------

    @property
    def bpm(self) -> float:
        if not self.uninherited:
            raise ValueError("green lines have no BPM")
        return 60000.0 / self.beat_length

    @property
    def sv(self) -> float:
        if self.uninherited:
            return 1.0
        return -100.0 / self.beat_length

    @property
    def kiai(self) -> bool:
        return bool(self.effects & 1)

    def render(self) -> str:
        return ",".join(
            [
                fmt_num(self.time),
                fmt_num(self.beat_length),
                str(self.meter),
                str(self.sample_set),
                str(self.sample_index),
                str(self.volume),
                "1" if self.uninherited else "0",
                str(self.effects),
            ]
        )


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


@dataclass
class Background:
    filename: str
    x: int = 0
    y: int = 0

    def render(self) -> str:
        return f'0,0,"{self.filename}",{self.x},{self.y}'


@dataclass
class Video:
    start_time: int
    filename: str
    x: int = 0
    y: int = 0

    def render(self) -> str:
        return f'Video,{self.start_time},"{self.filename}",{self.x},{self.y}'


@dataclass
class Break:
    start_time: int
    end_time: int

    def render(self) -> str:
        return f"2,{self.start_time},{self.end_time}"


@dataclass
class RawEvent:
    """Anything we do not model yet — kept verbatim."""

    line: str

    def render(self) -> str:
        return self.line


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------


@dataclass
class General:
    audio_filename: str = "audio.mp3"
    audio_lead_in: Optional[int] = 0
    audio_hash: Optional[str] = None
    preview_time: Optional[int] = -1
    countdown: Optional[int] = 0
    sample_set: Optional[str] = "Normal"
    stack_leniency: Optional[float] = 0.7
    mode: Optional[int] = 0
    letterbox_in_breaks: Optional[int] = 0
    story_fire_in_front: Optional[int] = None
    use_skin_sprites: Optional[int] = None
    always_show_playfield: Optional[int] = None
    overlay_position: Optional[str] = None
    skin_preference: Optional[str] = None
    epilepsy_warning: Optional[int] = None
    countdown_offset: Optional[int] = None
    special_style: Optional[int] = None
    widescreen_storyboard: Optional[int] = 0
    samples_match_playback_rate: Optional[int] = None

    # mapping of dataclass field -> file key
    _KEYS: ClassVar[dict[str, str]] = {
        "audio_filename": "AudioFilename",
        "audio_lead_in": "AudioLeadIn",
        "audio_hash": "AudioHash",
        "preview_time": "PreviewTime",
        "countdown": "Countdown",
        "sample_set": "SampleSet",
        "stack_leniency": "StackLeniency",
        "mode": "Mode",
        "letterbox_in_breaks": "LetterboxInBreaks",
        "story_fire_in_front": "StoryFireInFront",
        "use_skin_sprites": "UseSkinSprites",
        "always_show_playfield": "AlwaysShowPlayfield",
        "overlay_position": "OverlayPosition",
        "skin_preference": "SkinPreference",
        "epilepsy_warning": "EpilepsyWarning",
        "countdown_offset": "CountdownOffset",
        "special_style": "SpecialStyle",
        "widescreen_storyboard": "WidescreenStoryboard",
        "samples_match_playback_rate": "SamplesMatchPlaybackRate",
    }

    def items(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for name, key in self._KEYS.items():
            value = getattr(self, name)
            if value is None:
                continue
            rows.append((key, fmt_num(value) if not isinstance(value, str) else value))
        return rows

    def set(self, key: str, value: str) -> bool:
        for name, file_key in self._KEYS.items():
            if file_key == key:
                current = getattr(self, name)
                if isinstance(current, str) or name in ("sample_set", "overlay_position", "skin_preference", "audio_hash"):
                    setattr(self, name, value)
                elif isinstance(current, int):
                    setattr(self, name, _parse_int(value))
                elif isinstance(current, float):
                    setattr(self, name, _parse_float(value))
                else:
                    setattr(self, name, value)
                return True
        return False


@dataclass
class Editor:
    bookmarks: list[int] = field(default_factory=list)
    distance_spacing: Optional[float] = 1.0
    beat_divisor: Optional[int] = 4
    grid_size: Optional[int] = 4
    timeline_zoom: Optional[float] = 1.0

    _KEYS: ClassVar[dict[str, str]] = {
        "bookmarks": "Bookmarks",
        "distance_spacing": "DistanceSpacing",
        "beat_divisor": "BeatDivisor",
        "grid_size": "GridSize",
        "timeline_zoom": "TimelineZoom",
    }

    def items(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for name, key in self._KEYS.items():
            value = getattr(self, name)
            if value is None:
                continue
            if name == "bookmarks":
                if not value:
                    continue
                rows.append((key, ",".join(str(v) for v in value)))
            else:
                rows.append((key, fmt_num(value)))
        return rows

    def set(self, key: str, value: str) -> bool:
        if key == "Bookmarks":
            self.bookmarks = [int(v) for v in value.split(",") if v.strip()]
            return True
        for name, file_key in self._KEYS.items():
            if file_key == key:
                if name == "bookmarks":
                    self.bookmarks = []
                elif name in ("beat_divisor", "grid_size"):
                    setattr(self, name, _parse_int(value))
                else:
                    setattr(self, name, _parse_float(value))
                return True
        return False


@dataclass
class Metadata:
    title: str = ""
    title_unicode: str = ""
    artist: str = ""
    artist_unicode: str = ""
    creator: str = ""
    version: str = "Normal"
    source: str = ""
    tags: str = ""
    beatmap_id: int = 0
    beatmap_set_id: int = -1

    _KEYS: ClassVar[dict[str, str]] = {
        "title": "Title",
        "title_unicode": "TitleUnicode",
        "artist": "Artist",
        "artist_unicode": "ArtistUnicode",
        "creator": "Creator",
        "version": "Version",
        "source": "Source",
        "tags": "Tags",
        "beatmap_id": "BeatmapID",
        "beatmap_set_id": "BeatmapSetID",
    }

    def items(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for name, key in self._KEYS.items():
            value = getattr(self, name)
            rows.append((key, str(value) if not isinstance(value, int) else str(value)))
        return rows

    def set(self, key: str, value: str) -> bool:
        for name, file_key in self._KEYS.items():
            if file_key == key:
                if name in ("beatmap_id", "beatmap_set_id"):
                    setattr(self, name, _parse_int(value))
                else:
                    setattr(self, name, value)
                return True
        return False


@dataclass
class Difficulty:
    hp_drain_rate: Optional[float] = 5.0
    circle_size: Optional[float] = 4.0
    overall_difficulty: Optional[float] = 8.0
    approach_rate: Optional[float] = 9.0
    slider_multiplier: Optional[float] = 1.4
    slider_tick_rate: Optional[float] = 1.0

    _KEYS: ClassVar[dict[str, str]] = {
        "hp_drain_rate": "HPDrainRate",
        "circle_size": "CircleSize",
        "overall_difficulty": "OverallDifficulty",
        "approach_rate": "ApproachRate",
        "slider_multiplier": "SliderMultiplier",
        "slider_tick_rate": "SliderTickRate",
    }

    def items(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for name, key in self._KEYS.items():
            value = getattr(self, name)
            if value is not None:
                rows.append((key, fmt_num(value)))
        return rows

    def set(self, key: str, value: str) -> bool:
        for name, file_key in self._KEYS.items():
            if file_key == key:
                setattr(self, name, _parse_float(value))
                return True
        return False

    @property
    def effective_approach_rate(self) -> float:
        """Old maps without ``ApproachRate`` fall back to ``OverallDifficulty``."""
        if self.approach_rate is not None:
            return self.approach_rate
        return self.overall_difficulty or 5.0


# ---------------------------------------------------------------------------
# beatmap
# ---------------------------------------------------------------------------


@dataclass
class Beatmap:
    format_version: int = 14
    general: General = field(default_factory=General)
    editor: Editor = field(default_factory=Editor)
    metadata: Metadata = field(default_factory=Metadata)
    difficulty: Difficulty = field(default_factory=Difficulty)
    events: list[object] = field(default_factory=list)
    timing_points: list[TimingPoint] = field(default_factory=list)
    colours: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    hit_objects: list[HitObject] = field(default_factory=list)
    #: unknown key/value lines, per section, preserved for round-tripping
    extras: dict[str, list[str]] = field(default_factory=dict)

    # -- convenience --------------------------------------------------------

    def red_lines(self) -> list[TimingPoint]:
        return [t for t in self.timing_points if t.uninherited]

    def green_lines(self) -> list[TimingPoint]:
        return [t for t in self.timing_points if not t.uninherited]

    def first_red_line(self) -> Optional[TimingPoint]:
        reds = self.red_lines()
        return reds[0] if reds else None

    def check(self) -> list[str]:
        """Cheap structural sanity checks, in the spirit of what AiMod reports."""
        problems: list[str] = []
        if not self.timing_points:
            problems.append("no timing points")
        elif not self.timing_points[0].uninherited:
            problems.append("first timing point is not a red line")
        for previous, current in zip(self.timing_points, self.timing_points[1:]):
            if current.time < previous.time:
                problems.append("timing points are not sorted by time")
                break
        for previous, current in zip(self.hit_objects, self.hit_objects[1:]):
            if current.time < previous.time:
                problems.append("hit objects are not sorted by time")
                break
        for obj in self.hit_objects:
            if not (0 <= obj.x <= PLAYFIELD_WIDTH and 0 <= obj.y <= PLAYFIELD_HEIGHT):
                problems.append(f"object at {obj.time}ms is outside the playfield")
            if isinstance(obj, Slider) and obj.length <= 0:
                problems.append(f"slider at {obj.time}ms has non-positive length")
            if isinstance(obj, Spinner) and obj.end_time <= obj.time:
                problems.append(f"spinner at {obj.time}ms ends before it starts")
        return problems
