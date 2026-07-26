#!/usr/bin/env python3
"""YouTube 정확 링크 리졸버: 앨범마다 ytsearch1로 실제 영상 URL을 찾아 캐시.

- 대상: 디지털 DB(~/music-wiki-vault/music-wiki.db) + 실물(physical_albums.json)
- 캐시: ~/music-wiki-vault/youtube_links.json  (key = norm(artist)|norm(album))
- 멱등: 이미 캐시된 앨범은 건너뜀. 실패는 "" 기록(재시도하려면 해당 키 삭제).
- 실행 후 `music-wiki update --no-scan` 으로 md에 반영.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import yt_dlp

DB = os.path.expanduser("~/music-wiki-vault/music-wiki.db")
PHYS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "inventory", "data", "physical_albums.json")
CACHE = os.path.expanduser("~/music-wiki-vault/youtube_links.json")


def norm(s):
    return re.sub(r"[^a-z0-9가-힣]", "", str(s or "").lower())


def key(artist, album):
    return f"{norm(artist)}|{norm(album)}"


def targets():
    import sqlite3
    seen = {}
    c = sqlite3.connect(DB)
    for ar, ti in c.execute("SELECT ar.name, al.title FROM album al"
                            " JOIN artist ar ON al.artist_id=ar.id"):
        seen.setdefault(key(ar, ti), (ar, ti))
    if os.path.exists(PHYS):
        for a in json.load(open(PHYS, encoding="utf-8")):
            if a.get("artist") and a.get("album"):
                seen.setdefault(key(a["artist"], a["album"]), (a["artist"], a["album"]))
    return seen


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    todo = {k: v for k, v in targets().items() if k not in cache}
    print(f"대상 {len(todo)}건 (캐시 {len(cache)}건 보유)", flush=True)
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                            "extract_flat": True, "skip_download": True})
    n = 0
    for k, (artist, album) in todo.items():
        if n >= limit:
            break
        q = f"{artist} {album}".strip()
        try:
            info = ydl.extract_info(f"ytsearch1:{q}", download=False)
            ents = (info or {}).get("entries") or []
            if ents and ents[0].get("id"):
                cache[k] = {"url": f"https://www.youtube.com/watch?v={ents[0]['id']}",
                            "title": ents[0].get("title", "")}
            else:
                cache[k] = {"url": "", "title": ""}
        except Exception:
            cache[k] = {"url": "", "title": ""}
        n += 1
        if n % 25 == 0:
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  ...{n}/{len(todo)}", flush=True)
        time.sleep(0.7)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    ok = sum(1 for v in cache.values() if v.get("url"))
    print(f"DONE: 이번 {n}건 처리 | 캐시 총 {len(cache)}건 (링크 확보 {ok})")


if __name__ == "__main__":
    main()
