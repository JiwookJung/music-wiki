from __future__ import annotations

import re
from pathlib import PurePosixPath

from .models import RawTags, SourceFile, TrackRecord
from .normalize import clean_name, split_feat

_LEADING_NO = re.compile(r"^\s*(\d{1,3})[\s.\-_]+")
_MELON = re.compile(r"^(?P<artist>.+?)-(?P<no>\d{1,3})-(?P<title>.+)$")


def _strip_leading_no(stem: str) -> tuple[str, int | None]:
    m = _LEADING_NO.match(stem)
    if m:
        return stem[m.end():].strip(), int(m.group(1))
    return stem.strip(), None


class EntityResolver:
    def resolve(self, tags: RawTags, path: str, source: SourceFile) -> TrackRecord:
        p = PurePosixPath(path)
        stem = p.stem
        artist = clean_name(tags.album_artist) or clean_name(tags.artist)
        album = clean_name(tags.album)
        title = clean_name(tags.title)
        track_no = tags.track_no

        # melon flat pattern: artist-NN-title.mp3
        if (not artist or not title):
            m = _MELON.match(stem)
            if m:
                artist = artist or clean_name(m.group("artist"))
                title = title or clean_name(m.group("title"))
                track_no = track_no or int(m.group("no"))

        # folder fallback: <artist>/<album>/<NN title>.ext
        parts = p.parts
        if not title:
            t, n = _strip_leading_no(stem)
            title = t
            track_no = track_no or n
        if not album and len(parts) >= 2:
            album = clean_name(parts[-2])
        if not artist and len(parts) >= 3:
            artist = clean_name(parts[-3])

        title_clean, _feat = split_feat(title or stem)
        return TrackRecord(
            artist_name=artist or "Unknown Artist",
            album_title=album or "Unknown Album",
            track_title=title_clean or stem,
            track_no=track_no,
            disc_no=tags.disc_no,
            year=tags.year,
            label=tags.label,
            genres=[tags.genre] if tags.genre else [],
            duration_s=tags.duration_s,
            cover_path=None,
            source=source,
        )
