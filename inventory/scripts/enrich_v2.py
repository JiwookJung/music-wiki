#!/usr/bin/env python3
"""Enrich the user-edited inventory (lpcd_v2.json) using SoT artist+album.

Fills discogs_id / mbid / db_url / db_match for rows missing them.
Reuses the existing discogs_cache and mb caches. Saves progress periodically.
"""
import json
import os
import re
import time

import requests

SCR = ("/tmp/claude-1000/-home-neotango-media-archive-music-wiki/"
       "4e6dd816-7bba-408a-a949-f563a3925c6f/scratchpad")
V2 = os.path.join(SCR, "lpcd_v2.json")
DATA = "/home/neotango/lpcd_image/_data"
ENV = "/home/neotango/media-archive/music-wiki/.env"
DCACHE = os.path.join(DATA, "discogs_cache")
MCACHE = os.path.join(DATA, "mb_cache_v2")

env = {}
for line in open(ENV, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
TOKEN = env["DISCOGS_TOKEN"]
UA = f"music-wiki-lpcd/0.2 (+{env.get('MUSICBRAINZ_CONTACT', 'music-wiki')})"

dcache = json.load(open(DCACHE, encoding="utf-8")) if os.path.exists(DCACHE) else {}
mcache = json.load(open(MCACHE, encoding="utf-8")) if os.path.exists(MCACHE) else {}
ds = requests.Session()
ds.headers.update({"Authorization": f"Discogs token={TOKEN}", "User-Agent": UA})
ms = requests.Session()
ms.headers.update({"User-Agent": UA})
_last = [0.0]


def throttle():
    dt = time.monotonic() - _last[0]
    if dt < 1.1:
        time.sleep(1.1 - dt)
    _last[0] = time.monotonic()


def d_search(key, params):
    if key in dcache:
        return dcache[key]
    params = {**params, "type": "release", "per_page": 5}
    for _ in range(2):
        throttle()
        try:
            r = ds.get("https://api.discogs.com/database/search", params=params, timeout=25)
        except Exception:
            return []
        if r.status_code == 429:
            time.sleep(6)
            continue
        if r.status_code != 200:
            return []
        slim = [{"id": x.get("id"), "catno": x.get("catno", ""), "title": x.get("title", "")}
                for x in r.json().get("results", []) or []]
        dcache[key] = slim
        json.dump(dcache, open(DCACHE, "w", encoding="utf-8"), ensure_ascii=False)
        return slim
    return []


def m_search(artist, album):
    key = f"{artist.lower()}|{album.lower()}"
    if key in mcache:
        return mcache[key]
    import urllib.parse
    q = urllib.parse.quote(f'artist:"{artist}" AND releasegroup:"{album}"')
    throttle()
    try:
        d = ms.get(f"https://musicbrainz.org/ws/2/release-group/?query={q}&fmt=json&limit=1",
                   timeout=20).json()
    except Exception:
        return None
    rgs = d.get("release-groups") or []
    res = None
    if rgs:
        rg = rgs[0]
        ac = " ".join(c.get("name", "") for c in rg.get("artist-credit", []) if isinstance(c, dict))
        res = {"id": rg["id"], "score": int(rg.get("score", 0)), "title": rg.get("title", ""), "ac": ac}
    mcache[key] = res
    json.dump(mcache, open(MCACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return res


def toks(s):
    return set(re.findall(r"[a-z0-9가-힣]{2,}", (s or "").lower()))


def strip_paren(s):
    return re.sub(r"\s*[\(（][^\)）]*[\)）]", "", s).strip()


def variants(s):
    out = [s]
    sp = strip_paren(s)
    if sp and sp != s:
        out.append(sp)
    m = re.search(r"[\(（]([^\)）]+)[\)）]", s)
    if m and m.group(1).strip():
        out.append(m.group(1).strip())
    return out[:3]


rows = json.load(open(V2, encoding="utf-8"))
nd = nm = seen = 0
for i, r in enumerate(rows):
    a = str(r.get("artist") or "").strip()
    al = str(r.get("album") or "").strip()
    if not (a and al):
        continue
    medium = r.get("medium") or ""
    fmt = "Vinyl" if medium == "LP" else ("CD" if medium == "CD" else None)

    if not str(r.get("discogs_id") or "").strip():
        matched = None
        for av in variants(a):
            for alv in variants(al):
                params = {"artist": av, "release_title": alv}
                if fmt:
                    params["format"] = fmt
                res = d_search(f"at|{fmt}|{av.lower()}|{alv.lower()}", params)
                seen += 1
                for x in res[:3]:
                    if toks(av) & toks(x.get("title")):
                        matched = x
                        break
                if matched:
                    break
            if matched:
                break
        if not matched:  # loose q search
            q = f"{strip_paren(a)} {strip_paren(al)}"
            res = d_search(f"q|{q.lower()}", {"q": q})
            seen += 1
            want = toks(a + " " + al)
            best, bo = None, 0
            for x in res:
                ov = len(want & toks(x.get("title")))
                if ov > bo:
                    best, bo = x, ov
            if best and bo >= 2:
                matched = best
        if matched:
            r["discogs_id"] = str(matched["id"])
            if not str(r.get("db_url") or "").strip():
                r["db_url"] = f"https://www.discogs.com/release/{matched['id']}"
                r["db_match"] = matched.get("title", "")
            nd += 1

    if not str(r.get("mbid") or "").strip():
        got = None
        for av in variants(a):
            res = m_search(av, strip_paren(al))
            seen += 1
            if res and res["score"] >= 90 and (toks(av) & toks(res["ac"])):
                got = res
                break
        if got:
            r["mbid"] = got["id"]
            if not str(r.get("db_url") or "").strip():
                r["db_url"] = f"https://musicbrainz.org/release-group/{got['id']}"
                r["db_match"] = f'{got["ac"]} — {got["title"]}'
            nm += 1

    if i % 50 == 49:
        json.dump(rows, open(V2, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  ...{i+1}/{len(rows)} (discogs +{nd}, mbid +{nm}, q~{seen})", flush=True)

json.dump(rows, open(V2, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"DONE: discogs +{nd}, mbid +{nm}, queries ~{seen}")
