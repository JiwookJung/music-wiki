#!/usr/bin/env python3
"""Second Discogs pass: (1) looser re-search for rows still lacking any DB id,
then (2) backfill blank artist/album on catalog-number-recovered rows.

(1) Looser search: no format filter; try exact-catno first, then a free-text
    q="artist album" search, accepting only results whose title shares >=2
    tokens with our artist+album (keeps false positives down).
(2) Backfill: for rows that now have a discogs_id but blank artist AND album,
    parse the Discogs match title ("Artist - Title") into the columns and mark
    the note with [Discogs 복구].
Never touches rows that already have mbid/discogs_id. Shares the discogs_cache.
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
CACHE = os.path.join(DATA, "discogs_cache")


def load_env(path):
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
UA = f"music-wiki-lpcd/0.1 (+{env.get('MUSICBRAINZ_CONTACT', 'music-wiki')})"
if not TOKEN:
    raise SystemExit("DISCOGS_TOKEN missing in .env")

cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
sess = requests.Session()
sess.headers.update({"Authorization": f"Discogs token={TOKEN}", "User-Agent": UA})
_last = [0.0]


def save_cache():
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def throttle():
    dt = time.monotonic() - _last[0]
    if dt < 1.1:
        time.sleep(1.1 - dt)
    _last[0] = time.monotonic()


def search(key, params):
    if key in cache:
        return cache[key]
    params = {**params, "type": "release", "per_page": 5}
    for _ in range(2):
        throttle()
        try:
            r = sess.get("https://api.discogs.com/database/search", params=params, timeout=25)
        except Exception:
            return []
        if r.status_code == 429:
            time.sleep(6)
            continue
        if r.status_code != 200:
            return []
        slim = [{"id": x.get("id"), "catno": x.get("catno", ""), "title": x.get("title", "")}
                for x in r.json().get("results", []) or []]
        cache[key] = slim
        save_cache()
        return slim
    return []


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def toks(s):
    return set(re.findall(r"[a-z0-9가-힣]{2,}", (s or "").lower()))


def catno_cands(label_cat):
    s = (label_cat or "").strip()
    if not s:
        return []
    out, parts = [], [s]
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


def loose_pass():
    files = sorted(glob.glob(os.path.join(DATA, "*.json")))
    n = seen = 0
    for f in files:
        obj = json.load(open(f, encoding="utf-8"))
        changed = False
        for row in obj.get("rows", []):
            if row.get("discogs_id") or row.get("mbid"):
                continue
            artist = (row.get("artist") or "").strip()
            album = (row.get("album") or "").strip()
            label_cat = (row.get("label_cat") or "").strip()
            if not ((artist or album) or label_cat):
                continue
            matched = None
            lc_norm = norm(label_cat)

            # exact catno, no format filter
            for cand in catno_cands(label_cat):
                res = search(f"catno|any|{cand.lower()}", {"catno": cand})
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

            # free-text q search, require >=2 token overlap
            if not matched and (artist or album):
                q = " ".join(x for x in (artist, album) if x)
                res = search(f"q|{q.lower()}", {"q": q})
                seen += 1
                want = toks(artist + " " + album)
                best, best_ov = None, 0
                for r in res:
                    ov = len(want & toks(r.get("title")))
                    if ov > best_ov:
                        best, best_ov = r, ov
                if best and best_ov >= 2:
                    matched = best

            if matched:
                row["discogs_id"] = str(matched["id"])
                if not (row.get("db_url") or "").strip():
                    row["db_url"] = f"https://www.discogs.com/release/{matched['id']}"
                    row["db_match"] = matched.get("title", "")
                n += 1
                changed = True
        if changed:
            json.dump(obj, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  loose {os.path.basename(f)[:-5]:<16} (q ~{seen}, +{n})", flush=True)
    save_cache()
    print(f"LOOSE DONE: +{n} new discogs matches")


def clean_artist(a):
    a = re.sub(r"\s*\(\d+\)", "", a)          # drop Discogs disambiguation "(7)"
    return a.replace("*", "").strip()


def backfill_pass():
    files = sorted(glob.glob(os.path.join(DATA, "*.json")))
    n = 0
    for f in files:
        obj = json.load(open(f, encoding="utf-8"))
        changed = False
        for row in obj.get("rows", []):
            if not row.get("discogs_id"):
                continue
            if (row.get("artist") or "").strip() or (row.get("album") or "").strip():
                continue
            dm = (row.get("db_match") or "").strip()
            if " - " not in dm:
                continue
            artist, album = dm.split(" - ", 1)
            row["artist"] = clean_artist(artist)
            row["album"] = album.strip()
            note = (row.get("notes") or "").strip()
            row["notes"] = (note + " · [Discogs 복구]").strip(" ·")
            n += 1
            changed = True
        if changed:
            json.dump(obj, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"BACKFILL DONE: filled artist/album on {n} catalog-recovered rows")


if __name__ == "__main__":
    loose_pass()
    backfill_pass()
