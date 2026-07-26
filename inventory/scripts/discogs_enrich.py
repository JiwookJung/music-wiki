#!/usr/bin/env python3
"""Fill discogs_id (+ db_url/db_match when empty) from Discogs.

Reads DISCOGS_TOKEN from the music-wiki repo .env (never printed).
Match gates (to avoid the loose-score problem MusicBrainz had):
  - catalog-number path: the RESULT's own catno must appear (normalized) inside
    our recorded label_cat, AND — when we have an artist/album — the result title
    must share a token with our artist or album (rejects same-catno-different-artist).
  - artist+title path: the result title must share a token with our artist.
Non-destructive: always sets discogs_id on a match; sets db_url/db_match only when
they are still empty (so the verified MusicBrainz links stay).
Cached + rate-limited (~1.1s/req, 60/min authenticated); re-runnable.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time

import requests

DATA = "/home/neotango/lpcd_image/_data"
ENV = "/home/neotango/media-archive/music-wiki/.env"
CACHE = os.path.join(DATA, "discogs_cache")  # no .json so build_xlsx skips it


def load_env(path: str) -> dict:
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


env = load_env(ENV)
TOKEN = env.get("DISCOGS_TOKEN", "")
CONTACT = env.get("MUSICBRAINZ_CONTACT", "music-wiki")
UA = f"music-wiki-lpcd/0.1 (+{CONTACT})"
if not TOKEN:
    raise SystemExit("DISCOGS_TOKEN missing in .env")

cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
sess = requests.Session()
sess.headers.update({"Authorization": f"Discogs token={TOKEN}", "User-Agent": UA})
_last = [0.0]


def save_cache() -> None:
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def throttle() -> None:
    dt = time.monotonic() - _last[0]
    if dt < 1.1:
        time.sleep(1.1 - dt)
    _last[0] = time.monotonic()


def search(key: str, params: dict):
    if key in cache:
        return cache[key]
    params = {**params, "type": "release", "per_page": 5}
    for attempt in range(2):
        throttle()
        try:
            r = sess.get("https://api.discogs.com/database/search", params=params, timeout=25)
        except Exception:
            return []  # transient — do not cache
        if r.status_code == 429:
            time.sleep(6)
            continue
        if r.status_code != 200:
            return []
        res = r.json().get("results", []) or []
        slim = [{"id": x.get("id"), "catno": x.get("catno", ""), "title": x.get("title", "")}
                for x in res]
        cache[key] = slim
        save_cache()
        return slim
    return []


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def toks(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9가-힣]{2,}", (s or "").lower()))


def catno_cands(label_cat: str) -> list[str]:
    s = (label_cat or "").strip()
    if not s:
        return []
    out = []
    parts = [s]
    words = s.split()
    for i, w in enumerate(words):
        if any(c.isdigit() for c in w):
            parts.append(" ".join(words[i:]))
            break
    parts += [w for w in words if any(c.isdigit() for c in w)]
    for c in parts:
        c = c.strip()
        if c and len(norm(c)) >= 4 and c not in out:
            out.append(c)
    return out[:3]


def main() -> None:
    files = sorted(glob.glob(os.path.join(DATA, "*.json")))
    n = seen = 0
    for f in files:
        obj = json.load(open(f, encoding="utf-8"))
        changed = False
        medium = obj.get("medium", "")
        fmt = "Vinyl" if medium == "LP" else "CD"
        for row in obj.get("rows", []):
            if row.get("discogs_id"):
                continue
            artist = (row.get("artist") or "").strip()
            album = (row.get("album") or "").strip()
            label_cat = (row.get("label_cat") or "").strip()
            if not ((artist and album) or label_cat):
                continue
            matched = None

            # catalog-number path (most precise for physical pressings)
            lc_norm = norm(label_cat)
            for cand in catno_cands(label_cat):
                res = search(f"catno|{fmt}|{cand.lower()}", {"catno": cand, "format": fmt})
                seen += 1
                for r in res:
                    rc = norm(r.get("catno"))
                    if len(rc) < 4 or rc not in lc_norm:
                        continue
                    if (artist or album) and not (toks(artist + " " + album) & toks(r.get("title"))):
                        continue
                    matched = r
                    break
                if matched:
                    break

            # artist+title path
            if not matched and artist and album:
                res = search(f"at|{fmt}|{artist.lower()}|{album.lower()}",
                             {"artist": artist, "release_title": album, "format": fmt})
                seen += 1
                for r in res[:3]:
                    if toks(artist) & toks(r.get("title")):
                        matched = r
                        break

            if matched:
                row["discogs_id"] = str(matched["id"])
                url = f"https://www.discogs.com/release/{matched['id']}"
                if not (row.get("db_url") or "").strip():
                    row["db_url"] = url
                    row["db_match"] = matched.get("title", "")
                n += 1
                changed = True
        if changed:
            json.dump(obj, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  {os.path.basename(f)[:-5]:<18} (queries ~{seen}, filled {n})", flush=True)
    save_cache()
    print(f"DONE: discogs_id filled = {n}")


if __name__ == "__main__":
    main()
