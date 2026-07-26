#!/usr/bin/env python3
"""music-wiki 웹앱 프로토(E0) — ser8 프론트의 원형.

기동:  uvicorn app:app --host 0.0.0.0 --port 8765   (webapp/ 에서)
데이터: SQLite catalog 테이블(scripts/build_catalog.py) + vault md + youtube_links.
현 범위: 뷰어(홈/장르/앨범 md 렌더) + YouTube 플레이어 + 로컬 mp3 스트리밍(가능 시)
+ 검색. 추가/발급/LLM 패널은 E2.
"""
from __future__ import annotations

import html
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

import markdown
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse

VAULT = Path(os.path.expanduser("~/music-wiki-vault"))
DB = VAULT / "music-wiki.db"

app = FastAPI(title="music-wiki")


def q(sql, *args):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c.execute(sql, args).fetchall()


def safe_filename(name: str) -> str:
    return re.sub(r"[/\\:*?\"<>|]", "_", str(name)).strip()


_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
body{{font-family:system-ui,'Apple SD Gothic Neo',sans-serif;max-width:860px;margin:0 auto;
padding:1rem;background:#fafafa;color:#1a1a1a}}
a{{color:#2456c9;text-decoration:none}} a:hover{{text-decoration:underline}}
nav{{padding:.6rem 0;border-bottom:2px solid #eee;margin-bottom:1rem;display:flex;gap:1rem;
align-items:center;flex-wrap:wrap}}
nav b{{font-size:1.1rem}} input{{padding:.4rem .6rem;border:1px solid #ccc;border-radius:.4rem;
min-width:16rem}}
.badge{{display:inline-block;background:#e8edfb;border-radius:1rem;padding:.05rem .6rem;
font-size:.78rem;color:#365;margin-left:.3rem}}
.card{{background:#fff;border:1px solid #eee;border-radius:.6rem;padding:.7rem 1rem;
margin:.4rem 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:.5rem}}
iframe{{width:100%;aspect-ratio:16/9;border:0;border-radius:.6rem}}
blockquote{{color:#888;border-left:3px solid #ddd;margin:0;padding-left:.8rem}}
h1{{font-size:1.5rem}} .muted{{color:#888;font-size:.85rem}}
</style></head><body>
<nav><b><a href="/">🎵 music-wiki</a></b>
<form action="/search"><input name="q" placeholder="아티스트·앨범·해설 검색" value="{qv}"></form>
</nav>{body}</body></html>"""


def page(title, body, qv=""):
    return HTMLResponse(_PAGE.format(title=html.escape(title), body=body,
                                     qv=html.escape(qv)))


def album_cards(rows):
    out = []
    for r in rows:
        badges = ""
        if r["digital"]:
            badges += '<span class="badge">💿 디지털</span>'
        if r["physical_code"]:
            badges += f'<span class="badge">🟤 {html.escape(r["physical_code"])}</span>'
        if r["youtube_url"]:
            badges += '<span class="badge">▶</span>'
        out.append(f'<div class="card"><a href="/album/{quote(r["key"])}">'
                   f'{html.escape(r["artist"])} — {html.escape(r["album"])}</a>{badges}</div>')
    return "".join(out)


@app.get("/", response_class=HTMLResponse)
def home():
    rows = q("SELECT genre, COUNT(*) n, SUM(digital) d,"
             " SUM(physical_code IS NOT NULL) p FROM catalog"
             " GROUP BY genre ORDER BY n DESC")
    tot = q("SELECT COUNT(*) n, SUM(youtube_url IS NOT NULL) y FROM catalog")[0]
    body = [f"<h1>홈</h1><p>합집합 카탈로그 <b>{tot['n']}</b> 앨범 · YouTube 링크 "
            f"<b>{tot['y']}</b></p><div class='grid'>"]
    for r in rows:
        body.append(f'<div class="card"><a href="/genre/{quote(r["genre"])}">'
                    f'{html.escape(r["genre"])}</a><br>'
                    f'<span class="muted">{r["n"]}개 (💿{r["d"] or 0} · 🟤{r["p"] or 0})</span></div>')
    body.append("</div>")
    return page("music-wiki", "".join(body))


@app.get("/genre/{g}", response_class=HTMLResponse)
def genre(g: str):
    rows = q("SELECT * FROM catalog WHERE genre=? ORDER BY artist, album", g)
    return page(g, f"<h1>{html.escape(g)} <span class='muted'>{len(rows)}</span></h1>"
                + album_cards(rows))


@app.get("/search", response_class=HTMLResponse)
def search(request: Request):
    term = request.query_params.get("q", "")
    like = f"%{term}%"
    rows = q("SELECT * FROM catalog WHERE artist LIKE ? OR album LIKE ?"
             " OR description LIKE ? ORDER BY artist LIMIT 100", like, like, like)
    return page(f"검색: {term}", f"<h1>검색 결과 <span class='muted'>{len(rows)}</span></h1>"
                + album_cards(rows), qv=term)


@app.get("/album/{key}", response_class=HTMLResponse)
def album(key: str):
    rows = q("SELECT * FROM catalog WHERE key=?", key)
    if not rows:
        return page("없음", "<p>앨범을 찾을 수 없습니다.</p>")
    r = rows[0]
    parts = [f"<h1>{html.escape(r['artist'])} — {html.escape(r['album'])}</h1>"]
    meta = [f"장르 {html.escape(r['genre'] or '')}"]
    if r["physical_code"]:
        meta.append(f"실물 <b>{html.escape(r['physical_code'])}</b>"
                    f" ({html.escape(r['media'] or '')}, {html.escape(r['locations'] or '')})")
    if r["digital"]:
        meta.append("디지털 보유")
    parts.append("<p class='muted'>" + " · ".join(meta) + "</p>")
    # YouTube 임베드(정확 링크) 또는 검색 링크
    if r["youtube_url"] and "watch?v=" in r["youtube_url"]:
        vid = r["youtube_url"].split("watch?v=")[1][:20]
        parts.append(f'<iframe src="https://www.youtube.com/embed/{html.escape(vid)}" '
                     'allow="autoplay; encrypted-media" allowfullscreen></iframe>')
    else:
        s = quote(f"{r['artist']} {r['album']}")
        parts.append(f'<p>▶ <a target="_blank" '
                     f'href="https://www.youtube.com/results?search_query={s}">YouTube 검색</a></p>')
    # vault md 렌더(frontmatter 제거)
    md_path = VAULT / "albums" / (safe_filename(f"{r['artist']} - {r['album']}") + ".md")
    if md_path.exists():
        txt = md_path.read_text(encoding="utf-8")
        if txt.startswith("---\n"):
            txt = txt.split("---\n", 2)[-1]
        txt = re.sub(r"\[\[([^\]|]+)\]\]", r"\1", txt)   # 위키링크 → 텍스트(프로토)
        parts.append("<div class='card'>"
                     + markdown.markdown(txt, extensions=["tables"]) + "</div>")
    elif r["description"]:
        parts.append(f"<div class='card'><h2>해설</h2><p>{html.escape(r['description'])}</p></div>")
    return page(f"{r['artist']} — {r['album']}", "".join(parts))


@app.get("/audio/{key}/{fname}")
def audio(key: str, fname: str):
    """로컬 mp3 스트리밍(vault library 심볼릭 경유; 백엔드 온라인 시에만 성공)."""
    base = VAULT / "library"
    for p in base.rglob(fname):
        if p.is_file() or p.is_symlink():
            return FileResponse(str(p))
    return HTMLResponse("원본 오프라인(백엔드 꺼짐) — YouTube로 재생하세요", status_code=404)
