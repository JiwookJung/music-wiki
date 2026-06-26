from __future__ import annotations

import re
from pathlib import Path

from .store import Store

_BAD = re.compile(r"[/\\:*?\"<>|]")


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

    def _write_artist(self, out: Path, artist, albums) -> None:
        lines = [f"# {artist.name}", ""]
        if albums:
            lines.append("## 앨범")
            for a in albums:
                year = f" ({a.year})" if a.year else ""
                link = safe_filename(f"{artist.name} - {a.title}")
                lines.append(f"- [[{link}]]{year}")
        path = out / "artists" / f"{safe_filename(artist.name)}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_album(self, out: Path, artist, album) -> None:
        lines = [f"# {album.title}", "", f"아티스트: [[{safe_filename(artist.name)}]]"]
        if album.year:
            lines.append(f"연도: {album.year}")
        if album.label:
            lines.append(f"레이블: {album.label}")
        if album.genres:
            lines.append("장르: " + ", ".join(album.genres))
        lines.append(_badges(album))
        if album.cover_path:
            lines.append(f"![cover]({album.cover_path})")
        lines += ["", "## 트랙", "", "| # | 제목 | 길이 |", "|---|------|------|"]
        for t in self.store.tracks_for_album(album.id):
            dur = f"{int(t.duration_s) // 60}:{int(t.duration_s) % 60:02d}" if t.duration_s else ""
            no = t.track_no if t.track_no is not None else ""
            lines.append(f"| {no} | {t.title} | {dur} |")
        fname = safe_filename(f"{artist.name} - {album.title}")
        (out / "albums" / f"{fname}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
