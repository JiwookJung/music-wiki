from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Protocol


class MusicBrainzClient(Protocol):
    def lookup_genres(self, artist: str, album: str) -> list[str]: ...


def first_release_group_mbid(search_data: dict) -> str | None:
    groups = search_data.get("release-groups") or []
    if not groups:
        return None
    return groups[0].get("id")


def parse_genres(lookup_data: dict) -> list[str]:
    """genres[].name + tags[].name from a release-group LOOKUP response
    (inc=genres+tags). The search endpoint does NOT include these."""
    names: list[str] = []
    for g in lookup_data.get("genres") or []:
        if g.get("name"):
            names.append(g["name"])
    for t in lookup_data.get("tags") or []:
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

    def _write_cache(self, cache_file: Path | None, genres: list[str]) -> None:
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(genres, ensure_ascii=False), encoding="utf-8")

    def lookup_genres(self, artist: str, album: str) -> list[str]:
        if not artist or not album:
            return []
        cache_file = self._cache_path(artist, album)
        if cache_file and cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        query = urllib.parse.quote(f'artist:"{artist}" AND releasegroup:"{album}"')
        search_url = (f"https://musicbrainz.org/ws/2/release-group"
                      f"?query={query}&fmt=json&limit=1")
        self._throttle()
        try:
            search = self._fetch(search_url)
        except Exception:
            return []   # transient search failure → do not cache

        mbid = first_release_group_mbid(search)
        if mbid is None:
            self._write_cache(cache_file, [])   # genuinely not found in MB
            return []

        lookup_url = (f"https://musicbrainz.org/ws/2/release-group/{mbid}"
                      f"?inc=genres+tags&fmt=json")
        self._throttle()
        try:
            genres = parse_genres(self._fetch(lookup_url))
        except Exception:
            return []   # transient lookup failure → do not cache
        self._write_cache(cache_file, genres)
        return genres
