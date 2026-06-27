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
    seen: set[str] = set()
    root = target_root.rstrip("/")
    for r in store.iter_organizable():
        bucket = r.genre_bucket or UNCLASSIFIED
        ext = (r.fmt or "").lower() or PurePosixPath(r.abs_path).suffix.lstrip(".").lower()
        fname = _track_filename(r.disc_no, r.track_no, r.track_title, ext)
        dst = "/".join([root, safe_filename(bucket), safe_filename(r.artist_name),
                        safe_filename(r.album_title), fname])
        if dst in seen:
            continue  # same track reached via multiple source files → copy once
        seen.add(dst)
        ops.append(CopyOp(src=r.abs_path, dst=dst))
    return ops
