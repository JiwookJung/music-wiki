#!/usr/bin/env python3
"""music-wiki 웹앱 프로토(E0) — ser8 프론트의 원형.

기동:  uvicorn app:app --host 0.0.0.0 --port 8765   (webapp/ 에서)
데이터: SQLite catalog 테이블(scripts/build_catalog.py) + vault md + youtube_links.
현 범위: 뷰어(홈/장르/앨범 md 렌더) + YouTube 플레이어 + 로컬 mp3 스트리밍(가능 시)
+ 검색. 추가/발급/LLM 패널은 E2.
"""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

import markdown
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

try:
    from acquire import ask_claude, issue_code
except ImportError:  # 컨테이너 경로
    from webapp.acquire import ask_claude, issue_code

VAULT = Path(os.environ.get("MW_VAULT", os.path.expanduser("~/music-wiki-vault")))
DB = VAULT / "music-wiki.db"

# Neo4j (있으면 그래프 탐색 활성화, 없으면 자동 비활성)
_drv = None
try:
    from neo4j import GraphDatabase
    _drv = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"),
              os.environ.get("NEO4J_PASSWORD", "musicwiki")))
    _drv.verify_connectivity()
except Exception:
    _drv = None


def cypher(query, **params):
    if not _drv:
        return []
    try:
        with _drv.session() as s:
            return [r.data() for r in s.run(query, **params)]
    except Exception:
        return []

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
ol.tracks{{list-style:none;padding:0;margin:.5rem 0 0}}
.trk{{padding:.35rem .5rem;border-radius:.35rem;cursor:pointer}}
.trk:hover{{background:#eef}} .trk.on{{background:#dde7ff;font-weight:600}}
.trk.off{{color:#bbb;cursor:default}} .trk.off:hover{{background:none}}
</style></head><body>
<nav><b><a href="/">🎵 music-wiki</a></b><a href="/shelf">📚 정리장</a><a href="/add">➕ 등록</a><a href="/ask">💬 질의</a>
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
    # 로컬 mp3 플레이어 + 트랙 목록
    trks = album_tracks(r["album_id"])
    if trks:
        playable = [x for x in trks if x["online"]]
        items = []
        for i, x in enumerate(trks):
            num = (f"{x['disc']}-{x['no']:02d}" if x["disc"] and x["no"]
                   else (f"{x['no']:02d}" if x["no"] else "–"))
            dur = (f"{int(x['dur'])//60}:{int(x['dur'])%60:02d}" if x["dur"] else "")
            cls = "trk" if x["online"] else "trk off"
            onclick = f"play({i})" if x["online"] else ""
            items.append(f'<li class="{cls}" data-i="{i}" onclick="{onclick}">'
                         f'<span class="muted">{num}</span> {html.escape(x["title"])}'
                         f'<span class="muted"> {dur}</span>'
                         + ("" if x["online"] else '<span class="muted"> (오프라인)</span>')
                         + "</li>")
        srcs = json.dumps([{"id": x["id"], "t": x["title"]} for x in trks])
        parts.append(
            '<div class="card"><h2>수록곡 <span class="muted">'
            f'{len(playable)}/{len(trks)} 재생 가능</span></h2>'
            '<audio id="au" controls style="width:100%"></audio>'
            f'<ol class="tracks">{"".join(items)}</ol></div>'
            f'<script>const TR={srcs};const au=document.getElementById("au");'
            'function play(i){au.src="/audio/"+TR[i].id;au.play();'
            'document.querySelectorAll(".trk").forEach(e=>e.classList.remove("on"));'
            'document.querySelector(`.trk[data-i="${i}"]`)?.classList.add("on");}'
            'au.addEventListener("ended",()=>{const c=document.querySelector(".trk.on");'
            'const n=c&&c.nextElementSibling;if(n&&!n.classList.contains("off"))'
            'play(+n.dataset.i);});</script>')

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
    # 그래프 탐색: 같은 아티스트의 다른 앨범 / 같은 선반의 이웃
    rel = cypher(
        "MATCH (a:Album {key:$k})-[:BY]->(ar:Artist)<-[:BY]-(o:Album) "
        "RETURN o.key AS key, ar.name AS artist, o.title AS title LIMIT 12", k=key)
    if rel:
        parts.append("<div class='card'><h2>같은 아티스트</h2>" + "".join(
            f'<div><a href="/album/{quote(x["key"])}">{html.escape(x["title"] or "")}</a></div>'
            for x in rel) + "</div>")
    shelf = cypher(
        "MATCH (a:Album {key:$k})-[:SHELVED_IN]->(l:Location)<-[:SHELVED_IN]-(o:Album) "
        "WHERE o.key <> $k RETURN l.name AS loc, o.key AS key, o.title AS title, "
        "o.physical_code AS code ORDER BY o.physical_code LIMIT 10", k=key)
    if shelf:
        parts.append(f"<div class='card'><h2>같은 선반 ({html.escape(shelf[0]['loc'])})</h2>"
                     + "".join(f'<div><span class="muted">{html.escape(x["code"] or "")}</span> '
                               f'<a href="/album/{quote(x["key"])}">{html.escape(x["title"] or "")}</a></div>'
                               for x in shelf) + "</div>")
    sim = cypher(
        "MATCH (a:Album {key:$k}) WHERE a.embedding IS NOT NULL "
        "CALL db.index.vector.queryNodes('album_embedding', 9, a.embedding) "
        "YIELD node, score WHERE node.key <> $k "
        "MATCH (node)-[:BY]->(ar:Artist) "
        "RETURN node.key AS key, ar.name AS artist, node.title AS title, "
        "round(score,3) AS score ORDER BY score DESC LIMIT 8", k=key)
    if sim:
        parts.append("<div class='card'><h2>비슷한 앨범 <span class='muted'>(임베딩)</span></h2>"
                     + "".join(
            f'<div><a href="/album/{quote(x["key"])}">{html.escape(x["artist"] or "")} — '
            f'{html.escape(x["title"] or "")}</a> <span class="muted">{x["score"]}</span></div>'
            for x in sim) + "</div>")
    return page(f"{r['artist']} — {r['album']}", "".join(parts))


@app.get("/shelf", response_class=HTMLResponse)
def shelves():
    """실물 정리장 지도(그래프 기반)."""
    rows = cypher("MATCH (l:Location)<-[:SHELVED_IN]-(a:Album) "
                  "RETURN l.name AS loc, count(a) AS n ORDER BY loc")
    if not rows:
        return page("정리장", "<p>Neo4j 미연결 — 그래프 기능 비활성.</p>")
    body = ["<h1>실물 정리장</h1><div class='grid'>"]
    for r in rows:
        body.append(f'<div class="card"><a href="/shelf/{quote(r["loc"])}">'
                    f'{html.escape(r["loc"])}</a><br><span class="muted">{r["n"]}종</span></div>')
    return page("정리장", "".join(body) + "</div>")


@app.get("/shelf/{loc}", response_class=HTMLResponse)
def shelf(loc: str):
    rows = cypher("MATCH (l:Location {name:$l})<-[:SHELVED_IN]-(a:Album) "
                  "RETURN a.key AS key, a.title AS title, a.physical_code AS code "
                  "ORDER BY a.physical_code", l=loc)
    body = [f"<h1>{html.escape(loc)} <span class='muted'>{len(rows)}종</span></h1>"]
    for r in rows:
        body.append(f'<div class="card"><span class="muted">{html.escape(r["code"] or "")}</span> '
                    f'<a href="/album/{quote(r["key"])}">{html.escape(r["title"] or "")}</a></div>')
    return page(loc, "".join(body))


GENRES = ["클래식", "클래식기타", "재즈", "탱고", "월드", "팝", "가요", "OST·경음악"]
LOCS = ["LP중앙선반2열1층", "LP중앙선반1열1층", "LP중앙선반1열2층", "LP중앙선반1열3층",
        "LP중앙선반2열2층", "LP중앙선반2열3층", "LP좌측선반1층", "LP좌측선반2층",
        "LP좌측선반3층", "LP우측선반1층", "LP우측선반2층", "LP보관박스1", "LP침대옆",
        "CD윗층", "CD아래층"]


@app.get("/add", response_class=HTMLResponse)
def add_form():
    opts = "".join(f"<option>{g}</option>" for g in GENRES)
    locs = "".join(f"<option>{loc}</option>" for loc in LOCS)
    body = f"""<h1>음반 등록 · 분류번호 발급</h1>
<div class="card"><form id="f" onsubmit="return go(event)">
<p><input name="artist" placeholder="아티스트 *" required style="width:100%"></p>
<p><input name="album" placeholder="앨범 제목 *" required style="width:100%"></p>
<p><select name="genre">{opts}</select>
   <select name="medium"><option>LP</option><option>CD</option></select>
   <select name="location">{locs}</select></p>
<p><input name="composer" placeholder="작곡가(클래식)" >
   <input name="performer" placeholder="연주자(클래식)"></p>
<p><input name="label_cat" placeholder="레이블/카탈로그번호" style="width:100%"></p>
<p><button type="submit">분류번호 발급</button>
   <button type="button" onclick="go(event,true)">미리보기</button></p>
</form></div>
<div id="out"></div>
<script>
async function go(e, dry) {{
  e.preventDefault();
  const fd = new FormData(document.getElementById('f'));
  fd.append('dry_run', dry ? '1' : '');
  const r = await fetch('/api/issue', {{method:'POST', body:fd}});
  const j = await r.json();
  document.getElementById('out').innerHTML = j.code
    ? `<div class="card"><h2>분류번호</h2><p style="font-size:2rem"><b>${{j.code}}</b></p>`
      + (j.dry_run ? '<p class="muted">미리보기 — 저장되지 않음</p>'
                   : `<p class="muted">발급 완료 · 대기목록 ${{j.pending_total}}건 (백엔드에서 엑셀 반영)</p>`)
      + (j.warnings.length ? '<p>⚠ '+j.warnings.join('<br>⚠ ')+'</p>' : '') + '</div>'
    : '<div class="card">발급 실패 — 입력을 확인하세요</div>';
  return false;
}}
</script>"""
    return page("음반 등록", body)


@app.post("/api/issue")
async def api_issue(request: Request):
    f = await request.form()
    res = issue_code(artist=f.get("artist", ""), album=f.get("album", ""),
                     genre=f.get("genre", ""), medium=f.get("medium", "LP"),
                     composer=f.get("composer", ""), performer=f.get("performer", ""),
                     location=f.get("location", ""), label_cat=f.get("label_cat", ""),
                     dry_run=bool(f.get("dry_run")))
    return JSONResponse(res)


@app.get("/ask", response_class=HTMLResponse)
def ask_form():
    body = """<h1>LLM 질의 <span class='muted'>(Claude 구독)</span></h1>
<div class="card"><form onsubmit="return q(event)">
<p><textarea id="p" rows="3" style="width:100%"
   placeholder="예: 비 오는 날 들을 재즈 앨범 3개 추천해줘"></textarea></p>
<p><button>질의</button></p></form></div><div id="a"></div>
<script>
async function q(e){e.preventDefault();
  document.getElementById('a').innerHTML='<div class="card">생각 중…</div>';
  const r=await fetch('/api/ask',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({prompt:document.getElementById('p').value})});
  const j=await r.json();
  document.getElementById('a').innerHTML='<div class="card"><pre style="white-space:pre-wrap">'
    +j.answer.replace(/</g,'&lt;')+'</pre></div>'; return false;}
</script>"""
    return page("LLM 질의", body)


@app.post("/api/ask")
async def api_ask(request: Request):
    data = await request.json()
    prompt = str(data.get("prompt", ""))[:2000]
    ctx = q("SELECT artist, album, genre, physical_code FROM catalog"
            " WHERE description IS NOT NULL ORDER BY RANDOM() LIMIT 40")
    lines = [f"- {r['artist']} — {r['album']} ({r['genre']}"
             + (f", 실물 {r['physical_code']}" if r["physical_code"] else "") + ")"
             for r in ctx]
    full = ("아래는 사용자의 음악 컬렉션 일부입니다(무작위 표본).\n"
            + "\n".join(lines) + "\n\n질문: " + prompt
            + "\n\n한국어로 간결히 답하세요.")
    return JSONResponse({"answer": ask_claude(full)})


MUSIC_SRC = os.environ.get("MW_MUSIC_SRC", "/mnt/win/memory/음악")  # DB에 기록된 원본 루트
MUSIC_MNT = os.environ.get("MW_MUSIC_MNT", "/data/music")          # 이 프로세스에서 보이는 경로


def _local_path(abs_path: str) -> Path | None:
    """DB의 abs_path를 현재 환경에서 접근 가능한 실제 경로로 변환."""
    if not abs_path:
        return None
    for cand in (Path(abs_path.replace(MUSIC_SRC, MUSIC_MNT, 1)), Path(abs_path)):
        if cand.exists():
            return cand
    return None


def album_tracks(album_id: int | None):
    """앨범의 재생 가능한 트랙 목록(로컬 파일 존재 여부 포함)."""
    if not album_id:
        return []
    rows = q("SELECT t.id, t.disc_no, t.track_no, t.title, t.duration_s, sf.abs_path"
             " FROM track t JOIN source_file sf ON sf.track_id = t.id"
             " WHERE t.album_id = ? AND sf.is_drm = 0"
             " GROUP BY t.id ORDER BY t.disc_no, t.track_no, t.title", album_id)
    out = []
    for r in rows:
        out.append({"id": r["id"], "no": r["track_no"], "disc": r["disc_no"],
                    "title": r["title"], "dur": r["duration_s"],
                    "online": _local_path(r["abs_path"]) is not None})
    return out


@app.get("/audio/{track_id}")
def audio(track_id: int):
    """트랙 스트리밍. 원본(마운트)이 없으면 404 → UI가 YouTube로 폴백."""
    rows = q("SELECT sf.abs_path FROM source_file sf WHERE sf.track_id = ?"
             " AND sf.is_drm = 0 LIMIT 1", track_id)
    if not rows:
        return HTMLResponse("트랙 없음", status_code=404)
    p = _local_path(rows[0]["abs_path"])
    if not p:
        return HTMLResponse("원본 오프라인(백엔드 꺼짐) — YouTube로 재생하세요",
                            status_code=404)
    return FileResponse(str(p), media_type="audio/mpeg", filename=p.name)


@app.get("/api/status")
def status():
    """백엔드(mp3 원본) 온라인 여부 — UI 배지용."""
    online = Path(MUSIC_MNT).is_dir() and any(Path(MUSIC_MNT).iterdir())
    n = q("SELECT COUNT(*) c FROM source_file WHERE is_drm=0 AND track_id IS NOT NULL")[0]["c"]
    return JSONResponse({"music_online": bool(online), "tracks": n})
