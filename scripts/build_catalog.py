#!/usr/bin/env python3
"""합집합 카탈로그 빌드: 디지털(music-wiki.db) ∪ 실물(physical_albums.json)
→ SQLite `catalog` 테이블 (ser8 웹앱의 단일 데이터 소스).

파생 테이블이므로 매번 재생성(멱등). `music-wiki update` 후 실행 권장.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3

# 경로는 webapp/app.py 와 같은 규약(MW_VAULT·MW_INVENTORY)을 따른다.
# 컨테이너에서는 HOME=/root 라 ~ 확장이 통하지 않으므로 env 가 유일한 정답.
VAULT = os.path.expanduser(os.environ.get("MW_VAULT", "~/music-wiki-vault"))
DB = os.path.expanduser(os.environ.get("MW_DB", os.path.join(VAULT, "music-wiki.db")))
INV = os.path.expanduser(os.environ.get(
    "MW_INVENTORY",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "inventory")))
PHYS = os.path.join(INV, "data", "physical_albums.json")
YT = os.path.join(VAULT, "youtube_links.json")

# 디지털(album.genre_bucket)과 실물(엑셀)이 같은 장르를 다른 이름으로 부른다.
# 정본은 실물 쪽 이름 — 분류코드 문자(pipeline.GENRE_LETTER)와 묶여 있기 때문.
# 통일은 파생 테이블인 catalog 에서만 한다. music-wiki.db 의 genre_bucket 은
# 분류·해설·md 생성 파이프라인이 의존하므로 건드리지 않는다.
GENRE_CANON = {"경음악_OST": "OST·경음악", "제3세계": "월드"}


def canon_genre(g):
    return GENRE_CANON.get(g, g) or "미분류"


def norm(s):
    return re.sub(r"[^a-z0-9가-힣]", "", str(s or "").lower())


def main():
    c = sqlite3.connect(DB)
    c.executescript("""
    DROP TABLE IF EXISTS catalog;
    CREATE TABLE catalog (
        key TEXT PRIMARY KEY, artist TEXT, album TEXT, genre TEXT,
        digital INTEGER DEFAULT 0, album_id INTEGER,
        physical_code TEXT, media TEXT, locations TEXT, copies INTEGER,
        description TEXT, rep TEXT, youtube_url TEXT, db_url TEXT
    );
    """)
    yt = json.load(open(YT, encoding="utf-8")) if os.path.exists(YT) else {}

    rows: dict[str, dict] = {}
    for aid, ar, ti, bucket, desc in c.execute(
            "SELECT al.id, ar.name, al.title, al.genre_bucket, al.description"
            " FROM album al JOIN artist ar ON al.artist_id=ar.id"):
        k = f"{norm(ar)}|{norm(ti)}"
        rows[k] = {"key": k, "artist": ar, "album": ti, "genre": canon_genre(bucket),
                   "digital": 1, "album_id": aid, "physical_code": None, "media": None,
                   "locations": None, "copies": 0, "description": desc, "rep": None,
                   "youtube_url": (yt.get(k) or {}).get("url") or None, "db_url": None}
    if os.path.exists(PHYS):
        for a in json.load(open(PHYS, encoding="utf-8")):
            if not (a.get("artist") and a.get("album")):
                continue
            k = f"{norm(a['artist'])}|{norm(a['album'])}"
            r = rows.setdefault(k, {
                "key": k, "artist": a["artist"], "album": a["album"],
                "genre": canon_genre(a.get("genre")), "digital": 0, "album_id": None,
                "physical_code": None, "media": None, "locations": None, "copies": 0,
                "description": None, "rep": None,
                "youtube_url": (yt.get(k) or {}).get("url") or None, "db_url": None})
            r.update(physical_code=a.get("code"),
                     media="·".join(a.get("media") or []),
                     locations=", ".join(a.get("locations") or []),
                     copies=a.get("copies", 1),
                     rep=a.get("rep") or r.get("rep"),
                     db_url=a.get("db_url") or r.get("db_url"))
            if not r.get("description") and a.get("desc"):
                r["description"] = a["desc"]
            # 겹치는 앨범은 실물 장르를 따른다 — 라벨에 인쇄된 분류코드와 어긋나지
            # 않게. (디지털은 탱고를 따로 두지 않아 월드로 뭉뚱그린다)
            if a.get("genre"):
                r["genre"] = canon_genre(a["genre"])

    c.executemany(
        "INSERT INTO catalog VALUES (:key,:artist,:album,:genre,:digital,:album_id,"
        ":physical_code,:media,:locations,:copies,:description,:rep,:youtube_url,:db_url)",
        rows.values())
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
    both = c.execute("SELECT COUNT(*) FROM catalog WHERE digital=1 AND physical_code IS NOT NULL").fetchone()[0]
    ytn = c.execute("SELECT COUNT(*) FROM catalog WHERE youtube_url IS NOT NULL").fetchone()[0]
    print(f"catalog {n}건 (디지털∪실물, 겹침 {both}) | YouTube 정확링크 {ytn}")


if __name__ == "__main__":
    main()
