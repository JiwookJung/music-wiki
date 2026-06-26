from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from music_wiki.core.art import find_cover
from music_wiki.core.models import SourceFile
from music_wiki.core.resolver import EntityResolver
from music_wiki.core.store import Store
from music_wiki.core.tags import TagReader

AUDIO_EXT = {".mp3", ".flac", ".ape", ".ogg", ".wav", ".m4a", ".wma"}
DRM_EXT = {".enc"}


@dataclass
class ScanStats:
    scanned: int = 0
    ingested: int = 0
    drm: int = 0
    skipped: int = 0


def file_signature(path: str) -> tuple[str, float, int]:
    st = os.stat(path)
    raw = f"{os.path.abspath(path)}:{st.st_size}:{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest(), st.st_mtime, st.st_size


def scan_library(
    source_dir: str, store: Store, tag_reader: TagReader, *, skip_unchanged: bool = True
) -> ScanStats:
    stats = ScanStats()
    resolver = EntityResolver()
    for root, _dirs, files in os.walk(source_dir):
        for name in files:
            ext = Path(name).suffix.lower()
            full = os.path.join(root, name)
            if ext in DRM_EXT:
                sig, mtime, _size = file_signature(full)
                store.record_drm(SourceFile(abs_path=full, content_hash=sig,
                                            mtime=mtime, fmt=ext.lstrip("."), is_drm=True))
                stats.drm += 1
                continue
            if ext not in AUDIO_EXT:
                continue
            stats.scanned += 1
            sig, mtime, _size = file_signature(full)
            if skip_unchanged and store.has_signature(sig):
                stats.skipped += 1
                continue
            src = SourceFile(abs_path=full, content_hash=sig, mtime=mtime,
                             fmt=ext.lstrip("."))
            tags = tag_reader.read(full)
            rec = resolver.resolve(tags, full, src)
            rec.cover_path = find_cover(root)
            store.upsert(rec)
            stats.ingested += 1
    return stats
