from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawTags:
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_no: int | None = None
    disc_no: int | None = None
    year: int | None = None
    genre: str | None = None
    label: str | None = None
    duration_s: float | None = None
    album_artist: str | None = None


@dataclass
class SourceFile:
    abs_path: str
    content_hash: str
    mtime: float
    fmt: str
    is_drm: bool = False
    decode_status: str = "ok"


@dataclass
class TrackRecord:
    artist_name: str
    album_title: str
    track_title: str
    track_no: int | None
    disc_no: int | None
    year: int | None
    label: str | None
    source: SourceFile
    genres: list[str] = field(default_factory=list)
    duration_s: float | None = None
    cover_path: str | None = None
