from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from .store import Store

_BAD = re.compile(r"[/\\:*?\"<>|]")

_OKF_ACTOR = "process:music-wiki"


def okf_frontmatter(type_: str, title: str, *, description: str | None = None,
                    tags: list[str] | None = None, extra: dict | None = None) -> str:
    """OKF v0.2 준수 YAML frontmatter (docs/okf/SPEC.md). 필수 type + 권장 필드."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["---", f"type: {json.dumps(type_, ensure_ascii=False)}",
             f"title: {json.dumps(title, ensure_ascii=False)}"]
    if description:
        lines.append(f"description: {json.dumps(description, ensure_ascii=False)}")
    if tags:
        lines.append("tags: [" + ", ".join(json.dumps(x, ensure_ascii=False) for x in tags) + "]")
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append("status: stable")
    lines.append(f"generated: {{ by: {_OKF_ACTOR}, at: {now} }}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def safe_filename(name: str) -> str:
    return _BAD.sub("_", name).strip()


def _badges(album) -> str:
    parts = []
    if album.has_digital:
        parts.append("💿 디지털 보유")
    if album.has_vinyl:
        parts.append("🟤 바이닐 보유")
    return " · ".join(parts) if parts else "보유형태 미확인"


class WikiGenerator:
    def __init__(self, store: Store):
        self.store = store

    def generate(self, out_dir: str) -> None:
        out = Path(out_dir)
        (out / "artists").mkdir(parents=True, exist_ok=True)
        (out / "albums").mkdir(parents=True, exist_ok=True)
        for artist in self.store.iter_artists():
            albums = self.store.albums_for_artist(artist.id)
            self._write_artist(out, artist, albums)
            for album in albums:
                self._write_album(out, artist, album)
        self._write_drm(out)

    def _write_artist(self, out: Path, artist, albums) -> None:
        fm = okf_frontmatter("Artist", artist.name,
                             description=f"{artist.name} — 앨범 {len(albums)}개",
                             tags=["디지털"])
        lines = [fm + f"# {artist.name}", ""]
        if albums:
            lines.append("## 앨범")
            for a in albums:
                year = f" ({a.year})" if a.year else ""
                link = safe_filename(f"{artist.name} - {a.title}")
                lines.append(f"- [[{link}]]{year}")
        path = out / "artists" / f"{safe_filename(artist.name)}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_drm(self, out: Path) -> None:
        paths = self.store.drm_files()
        if not paths:
            return
        lines = [
            okf_frontmatter("Report", "DRM 재생불가 목록", tags=["디지털"]) + "# DRM (재생불가)", "",
            "다음 파일은 DRM으로 보호되어 재생할 수 없습니다.", "",
        ]
        lines += [f"- `{p}`" for p in paths]
        (out / "DRM.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_album(self, out: Path, artist, album) -> None:
        tags = ["디지털"] + ([album.genre_bucket] if album.genre_bucket else [])
        if album.physical_code:
            tags.append("실물보유")
        fm = okf_frontmatter("Album", f"{artist.name} - {album.title}",
                             description=(album.description or "").split("다.")[0][:80] or None,
                             tags=tags)
        lines = [fm + f"# {album.title}", "", f"아티스트: [[{safe_filename(artist.name)}]]"]
        if album.year:
            lines.append(f"연도: {album.year}")
        if album.label:
            lines.append(f"레이블: {album.label}")
        if album.genre_bucket:
            lines.append(f"분류: {album.genre_bucket}")
        if album.physical_code:
            lines.append(f"실물 음반: {album.physical_code}")
        yt = quote_plus(f"{artist.name} {album.title}")
        lines.append(f"▶ [YouTube 검색](https://www.youtube.com/results?search_query={yt})")
        if album.genres:
            lines.append("장르: " + ", ".join(album.genres))
        lines.append(_badges(album))
        if album.cover_path:
            lines.append(f"![cover]({album.cover_path})")
        if album.description:
            lines += ["", "## 해설", "", album.description,
                      "", "> 🤖 AI 생성 — 장르·분위기 기준(사실 미검증)"]
        lines += ["", "## 트랙", "", "| # | 제목 | 길이 |", "|---|------|------|"]
        for t in self.store.tracks_for_album(album.id):
            dur = f"{int(t.duration_s) // 60}:{int(t.duration_s) % 60:02d}" if t.duration_s else ""
            no = t.track_no if t.track_no is not None else ""
            lines.append(f"| {no} | {t.title} | {dur} |")
        fname = safe_filename(f"{artist.name} - {album.title}")
        (out / "albums" / f"{fname}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
