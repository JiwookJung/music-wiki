from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote_plus

from .wiki import okf_frontmatter, safe_filename

_PHYS_MARK = "## 실물 음반"


def _yt(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"


def _norm(s):
    import re as _re
    return _re.sub(r"[^a-z0-9가-힣]", "", str(s or "").lower())


def _album_md(a: dict, yt_links: dict | None = None) -> str:
    artist, album = a["artist"], a["album"]
    tags = ["실물"] + (a.get("media") or []) + ([a["genre"]] if a.get("genre") else [])
    if a.get("digital"):
        tags.append("디지털보유")
    fm = okf_frontmatter("Album", f"{artist} - {album}",
                         description=(a.get("desc") or "").split("다.")[0][:80] or None,
                         tags=tags, extra={"code": a["code"]})
    lines = [fm + f"# {album}", "", f"아티스트: [[{safe_filename(artist)}]]"]
    lines.append(f"분류코드: **{a['code']}**")
    if a.get("genre"):
        lines.append(f"분류: {a['genre']}")
    if a.get("composer"):
        lines.append(f"작곡가: {a['composer']}  |  연주자: {a.get('performer', '')}")
    media = "·".join(a.get("media") or [])
    locs = ", ".join(a.get("locations") or [])
    lines.append(f"실물: {media} — {locs}" + (f" (총 {a['copies']}매)" if a.get("copies", 1) > 1 else ""))
    if a.get("label_cat"):
        lines.append(f"레이블/카탈로그: {a['label_cat']}")
    if a.get("digital"):
        lines.append("💿 디지털 보유")
    if a.get("rep"):
        lines.append(f"대표곡: {a['rep']}")
    exact = ((yt_links or {}).get(f"{_norm(artist)}|{_norm(album)}") or {}).get("url")
    links = ([f"[앨범 재생]({exact})"] if exact
             else [f"[앨범 검색]({_yt(f'{artist} {album}')})"])
    for tr in [t.strip() for t in str(a.get("rep") or "").split(",") if t.strip()][:2]:
        links.append(f"[{tr}]({_yt(f'{artist} {tr}')})")
    lines.append("▶ YouTube: " + " · ".join(links))
    if a.get("db_url"):
        lines.append(f"DB: {a['db_url']}")
    if a.get("desc"):
        lines += ["", "## 해설", "", a["desc"],
                  "", "> 🤖 AI 생성 — 장르·분위기 기준(사실 미검증)"]
    return "\n".join(lines) + "\n"


def generate_physical_wiki(out_dir: str, physical_json: str) -> dict:
    """physical_albums.json → 실물 앨범/아티스트 md (디지털 위키와 같은 vault에 통합).

    - 실물 전용 앨범: albums/에 md 생성. 디지털 md가 이미 있으면 건드리지 않음
      (그 페이지에는 이미 '실물 음반: 코드' 줄이 있음).
    - 아티스트 md: 있으면 '## 실물 음반' 섹션 append(1회 가드), 없으면 새로 생성.
    반환: {"albums_created": n, "artists_touched": n, "skipped_existing": n}
    """
    out = Path(out_dir)
    (out / "albums").mkdir(parents=True, exist_ok=True)
    (out / "artists").mkdir(parents=True, exist_ok=True)
    data = json.load(open(physical_json, encoding="utf-8"))
    ylp = out / "youtube_links.json"
    yt_links = json.loads(ylp.read_text(encoding="utf-8")) if ylp.exists() else {}
    by_artist: dict[str, list[dict]] = {}
    created = skipped = 0
    for a in data:
        if not (str(a.get("artist") or "").strip() and str(a.get("album") or "").strip()):
            continue
        by_artist.setdefault(a["artist"], []).append(a)
        fname = safe_filename(f"{a['artist']} - {a['album']}") + ".md"
        path = out / "albums" / fname
        if path.exists() and "분류코드:" not in path.read_text(encoding="utf-8"):
            skipped += 1          # 디지털 앨범 md 존재 → 유지(실물 줄은 build-wiki가 표시)
            continue
        path.write_text(_album_md(a, yt_links), encoding="utf-8")
        created += 1

    touched = 0
    for artist, items in by_artist.items():
        path = out / "artists" / (safe_filename(artist) + ".md")
        sec = [_PHYS_MARK, ""]
        for a in sorted(items, key=lambda x: x["code"]):
            link = safe_filename(f"{artist} - {a['album']}")
            media = "·".join(a.get("media") or [])
            sec.append(f"- [[{link}]] `{a['code']}` ({media})")
        block = "\n".join(sec) + "\n"
        if path.exists():
            txt = path.read_text(encoding="utf-8")
            if _PHYS_MARK in txt:                      # 이전 섹션 교체(멱등)
                head = txt.split(_PHYS_MARK)[0].rstrip()
                txt = head + "\n\n" + block
            else:
                txt = txt.rstrip() + "\n\n" + block
            path.write_text(txt, encoding="utf-8")
        else:
            fm = okf_frontmatter("Artist", artist, tags=["실물"])
            path.write_text(f"{fm}# {artist}\n\n{block}", encoding="utf-8")
        touched += 1
    return {"albums_created": created, "artists_touched": touched,
            "skipped_existing": skipped}


def write_home_index(out_dir: str, digital_counts: dict, physical_json: str | None) -> None:
    """홈.md + 장르 MOC 진입점: Obsidian에서 컬렉션 전체를 둘러보는 시작 페이지."""
    out = Path(out_dir)
    phys = []
    if physical_json and Path(physical_json).exists():
        phys = json.load(open(physical_json, encoding="utf-8"))
    lines = [okf_frontmatter("Home", "음악 라이브러리 홈",
                             description="디지털+실물 컬렉션 전체 진입점") + "# 🎵 음악 라이브러리 홈", ""]
    total_d = sum(digital_counts.values())
    lines.append(f"디지털 앨범 **{total_d}** · 실물 음반 **{len(phys)}** (분류코드 기준)")
    lines += ["", "## 디지털 (장르 버킷)", ""]
    for b, n in sorted(digital_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {b}: {n}개 앨범")
    if phys:
        lines += ["", "## 실물 (분류코드 접두)", ""]
        pref: dict[str, int] = {}
        for a in phys:
            p = str(a.get("code", "")).split("-")[0]
            pref[p] = pref.get(p, 0) + 1
        names = {"C": "클래식", "CG": "클래식(DG 2864)", "G": "클래식기타", "J": "재즈",
                 "T": "탱고", "W": "월드", "P": "팝", "K": "가요", "KN": "가요(비매품)",
                 "O": "OST·경음악", "X": "기타"}
        for p, n in sorted(pref.items(), key=lambda x: -x[1]):
            lines.append(f"- **{p}** {names.get(p, '')}: {n}종")
        locs: dict[str, int] = {}
        for a in phys:
            for s in a.get("locations") or []:
                locs[s] = locs.get(s, 0) + 1
        lines += ["", "## 실물 정리장 지도", ""]
        for s, n in sorted(locs.items()):
            lines.append(f"- {s}: {n}종")
    lines += ["", "> `music-wiki update` 실행으로 변경분이 이 위키에 반영됩니다."]
    (out / "홈.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
