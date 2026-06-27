from __future__ import annotations

import html
import json

_STYLE = (
    "body{font-family:system-ui,'Apple SD Gothic Neo',sans-serif;max-width:760px;"
    "margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fafafa}"
    "h1{font-size:1.5rem;margin:0 0 .25rem}"
    ".badge{display:inline-block;background:#eee;border-radius:1rem;padding:.1rem .7rem;"
    "font-size:.8rem;color:#555}"
    "audio{width:100%;margin:1rem 0}"
    "ol{list-style:none;padding:0}"
    "li{padding:.5rem .6rem;border-radius:.4rem;cursor:pointer;display:flex;"
    "justify-content:space-between}"
    "li:hover{background:#eef}"
    "li.playing{background:#dde7ff;font-weight:600}"
    ".dur{color:#888;font-size:.85rem}"
    ".desc{margin-top:1.5rem;padding:1rem;background:#fff;border:1px solid #eee;"
    "border-radius:.5rem}"
    ".desc .ai{color:#999;font-size:.8rem;margin-top:.5rem}"
    "footer{margin-top:2rem;color:#aaa;font-size:.75rem}"
)

_SCRIPT = (
    "const TRACKS=%s;"
    "const audio=document.getElementById('player');"
    "const items=[...document.querySelectorAll('li[data-i]')];"
    "let cur=-1;"
    "function play(i){"
    "if(i<0||i>=TRACKS.length)return;"
    "cur=i;audio.src=encodeURIComponent(TRACKS[i].src);audio.play();"
    "items.forEach((el,j)=>el.classList.toggle('playing',j===i));}"
    "items.forEach(el=>el.addEventListener('click',()=>play(+el.dataset.i)));"
    "audio.addEventListener('ended',()=>play(cur+1));"
)


def _fmt_dur(seconds: float | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def render_album_html(*, artist: str, album: str, year: int | None,
                      bucket: str | None, description: str | None,
                      tracks: list[dict]) -> str:
    head = html.escape(f"{artist} — {album}")
    if year:
        head += html.escape(f" ({year})")
    badge = html.escape(bucket) if bucket else "미분류"

    items = []
    for i, t in enumerate(tracks):
        dur = _fmt_dur(t.get("duration_s"))
        dur_html = f'<span class="dur">{dur}</span>' if dur else ""
        items.append(
            f'<li data-i="{i}"><span>{html.escape(t["label"])}</span>{dur_html}</li>'
        )
    items_html = "".join(items)

    desc_html = ""
    if description and description.strip():
        desc_html = (
            '<section class="desc"><h2>해설</h2>'
            f'<p>{html.escape(description.strip())}</p>'
            '<p class="ai">🤖 AI 생성 — 장르·분위기 기준이며 사실(연도·인물 등)은 '
            '검증되지 않았습니다.</p></section>'
        )

    data = [{"src": t["src"], "label": t["label"]} for t in tracks]
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    script = _SCRIPT % data_json

    return (
        "<!doctype html>\n"
        '<html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{head}</title><style>{_STYLE}</style></head><body>"
        f"<h1>{head}</h1>"
        f'<div class="badge">{badge}</div>'
        '<audio id="player" controls preload="none"></audio>'
        f"<ol>{items_html}</ol>"
        f"{desc_html}"
        "<footer>music-wiki · 같은 폴더의 음원을 재생합니다</footer>"
        f"<script>{script}</script>"
        "</body></html>\n"
    )
