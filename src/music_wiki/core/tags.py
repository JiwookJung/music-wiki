from __future__ import annotations

from typing import Callable, Protocol

from .encoding import recover_text
from .models import RawTags


class TagReader(Protocol):
    def read(self, path: str) -> RawTags: ...


def _first(mf, key: str) -> str | None:
    val = mf.get(key) if hasattr(mf, "get") else None
    if not val:
        return None
    return str(val[0]) if isinstance(val, (list, tuple)) else str(val)


def _to_int(s: str | None) -> int | None:
    if not s:
        return None
    head = s.split("/")[0].strip()
    return int(head) if head.isdigit() else None


def _year(s: str | None) -> int | None:
    if not s:
        return None
    digits = s[:4]
    return int(digits) if digits.isdigit() else None


def extract_tags(mf) -> RawTags:
    length = getattr(getattr(mf, "info", None), "length", None)
    return RawTags(
        artist=recover_text(_first(mf, "artist")),
        album=recover_text(_first(mf, "album")),
        title=recover_text(_first(mf, "title")),
        track_no=_to_int(_first(mf, "tracknumber")),
        disc_no=_to_int(_first(mf, "discnumber")),
        year=_year(_first(mf, "date") or _first(mf, "year")),
        genre=recover_text(_first(mf, "genre")),
        label=recover_text(_first(mf, "organization")),
        duration_s=float(length) if length is not None else None,
        album_artist=recover_text(_first(mf, "albumartist")),
    )


class MutagenTagReader:
    def __init__(self, loader: Callable[[str], object] | None = None):
        if loader is None:
            import mutagen

            loader = lambda p: mutagen.File(p, easy=True)  # noqa: E731
        self._loader = loader

    def read(self, path: str) -> RawTags:
        mf = self._loader(path)
        if mf is None:
            return RawTags()
        return extract_tags(mf)
