from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Protocol


class MusicBrainzClient(Protocol):
    def lookup_genres(self, artist: str, album: str) -> list[str]: ...


def parse_genres(data: dict) -> list[str]:
    """Genres + folksonomy tags of the first (best) release-group match."""
    groups = data.get("release-groups") or []
    if not groups:
        return []
    rg = groups[0]
    names: list[str] = []
    for g in rg.get("genres") or []:
        if g.get("name"):
            names.append(g["name"])
    for t in rg.get("tags") or []:
        if t.get("name"):
            names.append(t["name"])
    return names


class HttpMusicBrainzClient:
    def __init__(self, user_agent: str, *, fetch: Callable[[str], dict] | None = None,
                 sleep: Callable[[float], None] | None = None,
                 cache_dir: str | None = None, min_interval: float = 1.0):
        self._ua = user_agent
        self._fetch = fetch or self._default_fetch
        self._sleep = sleep if sleep is not None else time.sleep
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._min_interval = min_interval
        self._last = 0.0

    def _default_fetch(self, url: str) -> dict:
        import requests

        resp = requests.get(url, headers={"User-Agent": self._ua}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _cache_path(self, artist: str, album: str) -> Path | None:
        if not self._cache_dir:
            return None
        key = hashlib.sha1(f"{artist}|{album}".encode("utf-8")).hexdigest()
        return self._cache_dir / f"mb-{key}.json"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)
        self._last = time.monotonic()

    def lookup_genres(self, artist: str, album: str) -> list[str]:
        if not artist or not album:
            return []
        cache_file = self._cache_path(artist, album)
        if cache_file and cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        self._throttle()
        query = urllib.parse.quote(f'artist:"{artist}" AND releasegroup:"{album}"')
        url = f"https://musicbrainz.org/ws/2/release-group?query={query}&fmt=json&limit=1"
        try:
            data = self._fetch(url)
        except Exception:
            return []
        genres = parse_genres(data)
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(genres, ensure_ascii=False), encoding="utf-8")
        return genres
