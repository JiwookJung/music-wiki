from __future__ import annotations

from pathlib import Path

_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
_PREFERRED = ("cover", "folder", "front", "album")


def find_cover(directory: str) -> str | None:
    d = Path(directory)
    if not d.is_dir():
        return None
    images = sorted(
        p for p in d.iterdir() if p.is_file() and p.suffix.lower() in _IMG_EXT
    )
    if not images:
        return None
    for pref in _PREFERRED:
        for img in images:
            if img.stem.lower() == pref:
                return str(img)
    return str(images[0])
