#!/usr/bin/env python3
"""Fill mbid + db_url in the _data JSONs from MusicBrainz (free, no token).

Conservative to avoid wrong links:
  - non-classical (performer == artist): release-group search by artist+album,
    accept only when score>=90 AND our artist shares a token with the matched
    artist-credit.
  - classical (or any fallback): release search by catalog number, accept only
    when score>=90 (a catalog number identifies one specific release).
Everything else is left blank for the later Discogs pass.
Cached + rate-limited (~1.1s/req); re-runnable (skips rows already filled).
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
import urllib.parse

import requests

DATA = "/home/neotango/lpcd_image/_data"
UA = "music-wiki-lpcd/0.1 (neotango7614@gmail.com)"
CACHE = os.path.join(DATA, "mb_cache")  # no .json so build_xlsx's glob skips it

cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {"rg": {}, "catno": {}}
sess = requests.Session()
sess.headers["User-Agent"] = UA
_last = [0.0]


def save_cache() -> None:
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def throttle() -> None:
    dt = time.monotonic() - _last[0]
    if dt < 1.1:
        time.sleep(1.1 - dt)
    _last[0] = time.monotonic()


def _artist_credit(obj) -> str:
    return " ".join(c.get("name", "") for c in obj.get("artist-credit", []) if isinstance(c, dict))


def mb_rg(artist: str, album: str):
    key = f"{artist.lower()}|{album.lower()}"
    if key in cache["rg"]:
        return cache["rg"][key]
    throttle()
    q = urllib.parse.quote(f'artist:"{artist}" AND releasegroup:"{album}"')
    url = f"https://musicbrainz.org/ws/2/release-group/?query={q}&fmt=json&limit=1"
    try:
        d = sess.get(url, timeout=20).json()
    except Exception:
        return None  # transient — do not cache
    rgs = d.get("release-groups") or []
    res = None
    if rgs:
        rg = rgs[0]
        res = {"id": rg["id"], "score": int(rg.get("score", 0)),
               "title": rg.get("title", ""), "ac": _artist_credit(rg)}
    cache["rg"][key] = res
    save_cache()
    return res


def mb_catno(catno: str):
    key = catno.lower()
    if key in cache["catno"]:
        return cache["catno"][key]
    throttle()
    q = urllib.parse.quote(f'catno:"{catno}"')
    url = f"https://musicbrainz.org/ws/2/release/?query={q}&fmt=json&limit=1"
    try:
        d = sess.get(url, timeout=20).json()
    except Exception:
        return None
    rs = d.get("releases") or []
    res = None
    if rs:
        r = rs[0]
        res = {"id": r["id"], "score": int(r.get("score", 0)),
               "title": r.get("title", ""), "ac": _artist_credit(r)}
    cache["catno"][key] = res
    save_cache()
    return res


def catno_candidates(label_cat: str) -> list[str]:
    s = (label_cat or "").strip()
    if not s:
        return []
    cands = [s]
    toks = s.split()
    for i, t in enumerate(toks):  # from the first digit-bearing token onward
        if any(ch.isdigit() for ch in t):
            cands.append(" ".join(toks[i:]))
            break
    out: list[str] = []
    for c in cands:
        for v in (c.strip(), c.replace(" ", "")):
            if v and v not in out:
                out.append(v)
    return out[:3]


def tok(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9가-힣]+", (s or "").lower()))


def main() -> None:
    files = sorted(glob.glob(os.path.join(DATA, "*.json")))
    n_rg = n_catno = 0
    seen = 0
    for f in files:
        obj = json.load(open(f, encoding="utf-8"))
        changed = False
        for row in obj.get("rows", []):
            if row.get("mbid"):
                continue
            artist = (row.get("artist") or "").strip()
            album = (row.get("album") or "").strip()
            genre = (row.get("genre") or "").lower()
            is_classical = "클래식" in genre or "classical" in genre
            done = False

            if artist and album and not is_classical:
                r = mb_rg(artist, album)
                seen += 1
                if r and r["score"] >= 90 and (tok(artist) & tok(r["ac"])):
                    row["mbid"] = r["id"]
                    row["db_url"] = f'https://musicbrainz.org/release-group/{r["id"]}'
                    row["db_match"] = f'{r["ac"]} — {r["title"]}'
                    n_rg += 1
                    changed = True
                    done = True

            if not done and (row.get("label_cat") or "").strip():
                for cand in catno_candidates(row["label_cat"]):
                    r = mb_catno(cand)
                    seen += 1
                    if r and r["score"] >= 90:
                        row["mbid"] = r["id"]
                        row["db_url"] = f'https://musicbrainz.org/release/{r["id"]}'
                        row["db_match"] = f'{r["ac"]} — {r["title"]}'
                        n_catno += 1
                        changed = True
                        break
        if changed:
            json.dump(obj, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  {os.path.basename(f)[:-5]:<18} (queries so far ~{seen})", flush=True)
    save_cache()
    print(f"DONE: filled mbid via artist+album={n_rg}, via catalog#={n_catno}")


if __name__ == "__main__":
    main()
