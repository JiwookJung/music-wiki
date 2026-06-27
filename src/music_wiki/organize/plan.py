from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from music_wiki.core.store import Store
from music_wiki.core.wiki import safe_filename

from .buckets import UNCLASSIFIED


@dataclass
class CopyOp:
    src: str
    dst: str


def _track_filename(disc_no: int | None, track_no: int | None, title: str, ext: str) -> str:
    safe_title = safe_filename(title)
    if track_no is None:
        return f"{safe_title}.{ext}"
    num = f"{disc_no}-{track_no:02d}" if disc_no is not None else f"{track_no:02d}"
    return f"{num} - {safe_title}.{ext}"


def build_plan(store: Store, target_root: str) -> list[CopyOp]:
    ops: list[CopyOp] = []
    placed: dict[str, tuple] = {}   # dst -> logical track key placed there
    root = target_root.rstrip("/")
    for r in store.iter_organizable():
        bucket = r.genre_bucket or UNCLASSIFIED
        ext = (r.fmt or "").lower() or PurePosixPath(r.abs_path).suffix.lstrip(".").lower()
        key = (bucket, r.artist_name, r.album_title, r.disc_no, r.track_no, r.track_title)
        fname = _track_filename(r.disc_no, r.track_no, r.track_title, ext)
        base = "/".join([root, safe_filename(bucket), safe_filename(r.artist_name),
                         safe_filename(r.album_title), fname])
        dst = base
        if dst in placed:
            if placed[dst] == key:
                continue  # same track via multiple source files → copy once
            # a DIFFERENT track sanitizes to the same path → suffix, never drop
            stem, dot, ext_part = base.rpartition(".")
            i = 2
            while True:
                cand = f"{stem} ({i}){dot}{ext_part}" if dot else f"{base} ({i})"
                if cand not in placed:
                    dst = cand
                    break
                i += 1
        placed[dst] = key
        ops.append(CopyOp(src=r.abs_path, dst=dst))
    return ops
