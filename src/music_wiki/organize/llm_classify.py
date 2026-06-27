from __future__ import annotations

import json

from music_wiki.core.encoding import recover_text
from music_wiki.core.store import Store
from music_wiki.external.local_llm import LocalLLMClient

from .buckets import BUCKETS, UNCLASSIFIED

_VALID = set(BUCKETS) | {UNCLASSIFIED}

_SYSTEM = (
    "너는 음악 장르 분류기다. 아래 7개 버킷 중 정확히 하나를 고른다: "
    + ", ".join(BUCKETS)
    + ". 한국 대중음악은 '가요', 영화/드라마/게임 음악은 '경음악_OST', "
    "탱고·라틴·월드뮤직은 '제3세계'. 확신이 없으면 '미분류'."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "bucket": {"type": "string", "enum": BUCKETS + [UNCLASSIFIED]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["bucket", "confidence"],
}


def _prompt(artist: str, album: str, genres: list[str], titles: list[str]) -> str:
    tags = ", ".join((recover_text(g) or "") for g in genres) or "(없음)"
    sample = "; ".join(titles[:8]) or "(없음)"
    return (f"아티스트: {artist}\n앨범: {album}\n장르 태그: {tags}\n"
            f"수록곡 일부: {sample}\n이 앨범의 버킷은?")


def classify_low_confidence_llm(store: Store, client: LocalLLMClient, *,
                                threshold: float = 0.8) -> int:
    n = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_source == "manual":
                continue
            conf = album.genre_confidence if album.genre_confidence is not None else 0.0
            if conf >= threshold and album.genre_bucket not in (None, UNCLASSIFIED):
                continue
            titles = [t.title for t in store.tracks_for_album(album.id)]
            user = _prompt(artist.name, album.title, album.genres, titles)
            try:
                raw = client.complete(_SYSTEM, user, json_schema=_SCHEMA)
                data = json.loads(raw)
                bucket = data["bucket"]
                new_conf = float(data.get("confidence", 0.0))
            except Exception:
                continue   # parse/network failure on one album must not abort the rest
            if bucket not in _VALID or bucket == UNCLASSIFIED:
                continue
            if new_conf > conf:
                store.set_album_genre(album.id, bucket, new_conf, "llm")
                n += 1
    return n
