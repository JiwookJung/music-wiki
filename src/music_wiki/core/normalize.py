from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_FEAT = re.compile(
    r"\s*[\(\[]\s*(?:feat\.?|featuring|with)\s+(.+?)\s*[\)\]]\s*$",
    re.IGNORECASE,
)


def clean_name(s: str | None) -> str | None:
    if s is None:
        return None
    return _WS.sub(" ", s).strip()


def match_key(s: str) -> str:
    return (clean_name(s) or "").casefold()


def split_feat(title: str) -> tuple[str, list[str]]:
    m = _FEAT.search(title)
    if not m:
        return clean_name(title) or title, []
    artists = [a.strip() for a in re.split(r",|&|/", m.group(1)) if a.strip()]
    clean = _FEAT.sub("", title)
    return clean_name(clean) or clean, artists
