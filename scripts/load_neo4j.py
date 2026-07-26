#!/usr/bin/env python3
"""SQLite catalog + 트랙 → Neo4j 그래프 적재.

그래프 모델:
  (:Genre)<-[:IN_GENRE]-(:Album)-[:BY]->(:Artist)
  (:Album)-[:CONTAINS]->(:Track)
  (:Album {physical_code, locations})  ← 실물 정보는 Album 속성
  (:Album)-[:SHELVED_IN]->(:Location)  ← 실물 보관 위치

재실행 안전(MERGE). 기본 접속 bolt://localhost:7687 (env 로 재정의).
사용: python scripts/load_neo4j.py [--wipe]
"""
from __future__ import annotations

import argparse
import os
import sqlite3

from neo4j import GraphDatabase

DB = os.path.expanduser(os.environ.get("MW_DB", "~/music-wiki-vault/music-wiki.db"))
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "musicwiki"))

SCHEMA = [
    "CREATE CONSTRAINT album_key IF NOT EXISTS FOR (a:Album) REQUIRE a.key IS UNIQUE",
    "CREATE CONSTRAINT artist_name IF NOT EXISTS FOR (x:Artist) REQUIRE x.name IS UNIQUE",
    "CREATE CONSTRAINT genre_name IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE",
    "CREATE CONSTRAINT loc_name IF NOT EXISTS FOR (l:Location) REQUIRE l.name IS UNIQUE",
    "CREATE INDEX album_code IF NOT EXISTS FOR (a:Album) ON (a.physical_code)",
    "CREATE FULLTEXT INDEX album_text IF NOT EXISTS "
    "FOR (a:Album) ON EACH [a.title, a.description]",
]

UPSERT_ALBUM = """
UNWIND $rows AS r
MERGE (a:Album {key: r.key})
  SET a.title = r.album, a.description = r.description, a.digital = r.digital,
      a.physical_code = r.physical_code, a.media = r.media,
      a.locations = r.locations, a.copies = r.copies,
      a.youtube_url = r.youtube_url, a.rep = r.rep, a.album_id = r.album_id
MERGE (ar:Artist {name: r.artist})
MERGE (a)-[:BY]->(ar)
MERGE (g:Genre {name: r.genre})
MERGE (a)-[:IN_GENRE]->(g)
WITH a, r WHERE r.locations IS NOT NULL AND r.locations <> ''
UNWIND split(r.locations, ', ') AS loc
MERGE (l:Location {name: trim(loc)})
MERGE (a)-[:SHELVED_IN]->(l)
"""

UPSERT_TRACKS = """
UNWIND $rows AS r
MATCH (a:Album {key: r.key})
MERGE (t:Track {album_key: r.key, title: r.title})
  SET t.duration_s = r.duration_s, t.no = r.no
MERGE (a)-[:CONTAINS]->(t)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wipe", action="store_true", help="기존 그래프 삭제 후 적재")
    ap.add_argument("--no-tracks", action="store_true")
    args = ap.parse_args()

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    albums = [dict(r) for r in c.execute("SELECT * FROM catalog")]

    tracks = []
    if not args.no_tracks:
        for r in c.execute(
                "SELECT ar.name artist, al.title album, t.title, t.track_no, t.duration_s"
                " FROM track t JOIN album al ON t.album_id=al.id"
                " JOIN artist ar ON al.artist_id=ar.id"):
            import re
            def n(s):
                return re.sub(r"[^a-z0-9가-힣]", "", str(s or "").lower())
            tracks.append({"key": f"{n(r['artist'])}|{n(r['album'])}", "title": r["title"],
                           "no": r["track_no"], "duration_s": r["duration_s"]})

    drv = GraphDatabase.driver(URI, auth=AUTH)
    with drv.session() as s:
        if args.wipe:
            s.run("MATCH (n) DETACH DELETE n")
            print("· 기존 그래프 삭제")
        for stmt in SCHEMA:
            s.run(stmt)
        for i in range(0, len(albums), 500):
            s.run(UPSERT_ALBUM, rows=albums[i:i + 500])
        print(f"· Album {len(albums)} 적재")
        for i in range(0, len(tracks), 2000):
            s.run(UPSERT_TRACKS, rows=tracks[i:i + 2000])
        print(f"· Track {len(tracks)} 적재")
        stats = s.run(
            "MATCH (a:Album) WITH count(a) AS al "
            "MATCH (x:Artist) WITH al, count(x) AS ar "
            "MATCH (g:Genre) WITH al, ar, count(g) AS g "
            "OPTIONAL MATCH (t:Track) WITH al, ar, g, count(t) AS t "
            "OPTIONAL MATCH (l:Location) RETURN al, ar, g, t, count(l) AS loc").single()
        print(f"· 그래프: Album {stats['al']} · Artist {stats['ar']} · Genre {stats['g']}"
              f" · Track {stats['t']} · Location {stats['loc']}")
    drv.close()


if __name__ == "__main__":
    main()
