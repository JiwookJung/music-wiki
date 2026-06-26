from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .models import SourceFile, TrackRecord
from .normalize import match_key

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artist (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS album (
    id INTEGER PRIMARY KEY, artist_id INTEGER NOT NULL REFERENCES artist(id),
    title TEXT NOT NULL, title_key TEXT NOT NULL, year INTEGER, label TEXT,
    genres TEXT NOT NULL DEFAULT '[]', cover_path TEXT,
    has_digital INTEGER NOT NULL DEFAULT 0, has_vinyl INTEGER NOT NULL DEFAULT 0,
    UNIQUE(artist_id, title_key)
);
CREATE TABLE IF NOT EXISTS track (
    id INTEGER PRIMARY KEY, album_id INTEGER NOT NULL REFERENCES album(id),
    title TEXT NOT NULL, title_key TEXT NOT NULL, disc_no INTEGER, track_no INTEGER,
    duration_s REAL, UNIQUE(album_id, disc_no, track_no, title_key)
);
CREATE TABLE IF NOT EXISTS source_file (
    id INTEGER PRIMARY KEY, track_id INTEGER REFERENCES track(id),
    abs_path TEXT NOT NULL, content_hash TEXT NOT NULL UNIQUE, mtime REAL,
    fmt TEXT, decode_status TEXT, is_drm INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class ArtistRow:
    id: int
    name: str


@dataclass
class AlbumRow:
    id: int
    title: str
    year: int | None
    label: str | None
    genres: list[str]
    has_digital: bool
    has_vinyl: bool
    cover_path: str | None


@dataclass
class TrackRow:
    id: int
    title: str
    disc_no: int | None
    track_no: int | None
    duration_s: float | None


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def open(cls, path: str) -> "Store":
        return cls(sqlite3.connect(path))

    def init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- writes ---
    def _artist_id(self, name: str) -> int:
        key = match_key(name)
        cur = self.conn.execute("SELECT id FROM artist WHERE name_key=?", (key,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur = self.conn.execute(
            "INSERT INTO artist(name, name_key) VALUES(?, ?)", (name, key)
        )
        return cur.lastrowid

    def _album_id(self, artist_id: int, rec: TrackRecord) -> int:
        key = match_key(rec.album_title)
        cur = self.conn.execute(
            "SELECT id FROM album WHERE artist_id=? AND title_key=?", (artist_id, key)
        )
        row = cur.fetchone()
        if row:
            album_id = row[0]
        else:
            cur = self.conn.execute(
                "INSERT INTO album(artist_id, title, title_key, year, label, genres,"
                " cover_path, has_digital) VALUES(?,?,?,?,?,?,?,1)",
                (artist_id, rec.album_title, key, rec.year, rec.label,
                 json.dumps(rec.genres, ensure_ascii=False), rec.cover_path),
            )
            return cur.lastrowid
        # fill gaps + ensure has_digital
        self.conn.execute(
            "UPDATE album SET has_digital=1,"
            " year=COALESCE(year, ?), label=COALESCE(label, ?),"
            " cover_path=COALESCE(cover_path, ?) WHERE id=?",
            (rec.year, rec.label, rec.cover_path, album_id),
        )
        return album_id

    def _track_id(self, album_id: int, rec: TrackRecord) -> int:
        key = match_key(rec.track_title)
        cur = self.conn.execute(
            "SELECT id FROM track WHERE album_id=? AND IFNULL(disc_no,-1)=IFNULL(?,-1)"
            " AND IFNULL(track_no,-1)=IFNULL(?,-1) AND title_key=?",
            (album_id, rec.disc_no, rec.track_no, key),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur = self.conn.execute(
            "INSERT INTO track(album_id, title, title_key, disc_no, track_no,"
            " duration_s) VALUES(?,?,?,?,?,?)",
            (album_id, rec.track_title, key, rec.disc_no, rec.track_no, rec.duration_s),
        )
        return cur.lastrowid

    def upsert(self, rec: TrackRecord) -> None:
        if self.has_signature(rec.source.content_hash):
            return  # already ingested — idempotent on content_hash
        self._prune_path(rec.source.abs_path)  # remove rows from a prior version of this file
        artist_id = self._artist_id(rec.artist_name)
        album_id = self._album_id(artist_id, rec)
        track_id = self._track_id(album_id, rec)
        src = rec.source
        self.conn.execute(
            "INSERT INTO source_file(track_id, abs_path, content_hash, mtime, fmt,"
            " decode_status, is_drm) VALUES(?,?,?,?,?,?,0)",
            (track_id, src.abs_path, src.content_hash, src.mtime, src.fmt,
             src.decode_status),
        )
        self.conn.commit()

    def record_drm(self, src: SourceFile) -> None:
        self.conn.execute(
            "INSERT INTO source_file(abs_path, content_hash, mtime, fmt, is_drm)"
            " VALUES(?,?,?,?,1) ON CONFLICT(content_hash) DO NOTHING",
            (src.abs_path, src.content_hash, src.mtime, src.fmt),
        )
        self.conn.commit()

    def has_signature(self, content_hash: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM source_file WHERE content_hash=?", (content_hash,)
        )
        return cur.fetchone() is not None

    # --- reads ---
    def iter_artists(self) -> list[ArtistRow]:
        cur = self.conn.execute("SELECT id, name FROM artist ORDER BY name")
        return [ArtistRow(*r) for r in cur.fetchall()]

    def albums_for_artist(self, artist_id: int) -> list[AlbumRow]:
        cur = self.conn.execute(
            "SELECT id, title, year, label, genres, has_digital, has_vinyl, cover_path"
            " FROM album WHERE artist_id=? ORDER BY year, title", (artist_id,)
        )
        return [
            AlbumRow(r[0], r[1], r[2], r[3], json.loads(r[4]), bool(r[5]), bool(r[6]), r[7])
            for r in cur.fetchall()
        ]

    def tracks_for_album(self, album_id: int) -> list[TrackRow]:
        cur = self.conn.execute(
            "SELECT id, title, disc_no, track_no, duration_s FROM track"
            " WHERE album_id=? ORDER BY disc_no, track_no, title", (album_id,)
        )
        return [TrackRow(*r) for r in cur.fetchall()]

    def drm_count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM source_file WHERE is_drm=1")
        return cur.fetchone()[0]

    def _prune_path(self, abs_path: str) -> None:
        """Remove rows left by a previous version of this file (a changed file
        gets a new content_hash). Deletes stale source_file rows for the path
        and garbage-collects any track/album/artist they orphan."""
        cur = self.conn.execute(
            "SELECT DISTINCT track_id FROM source_file WHERE abs_path=?", (abs_path,)
        )
        track_ids = [r[0] for r in cur.fetchall() if r[0] is not None]
        self.conn.execute("DELETE FROM source_file WHERE abs_path=?", (abs_path,))
        for track_id in track_ids:
            if self.conn.execute(
                "SELECT 1 FROM source_file WHERE track_id=? LIMIT 1", (track_id,)
            ).fetchone():
                continue
            row = self.conn.execute(
                "SELECT album_id FROM track WHERE id=?", (track_id,)
            ).fetchone()
            if not row:
                continue
            album_id = row[0]
            self.conn.execute("DELETE FROM track WHERE id=?", (track_id,))
            if self.conn.execute(
                "SELECT 1 FROM track WHERE album_id=? LIMIT 1", (album_id,)
            ).fetchone():
                continue
            arow = self.conn.execute(
                "SELECT artist_id FROM album WHERE id=?", (album_id,)
            ).fetchone()
            self.conn.execute("DELETE FROM album WHERE id=?", (album_id,))
            if arow and not self.conn.execute(
                "SELECT 1 FROM album WHERE artist_id=? LIMIT 1", (arow[0],)
            ).fetchone():
                self.conn.execute("DELETE FROM artist WHERE id=?", (arow[0],))

    def drm_files(self) -> list[str]:
        cur = self.conn.execute(
            "SELECT abs_path FROM source_file WHERE is_drm=1 ORDER BY abs_path"
        )
        return [r[0] for r in cur.fetchall()]
