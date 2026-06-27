# 라이브러리 앨범 페이지 (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 정리된 라이브러리(`organize --apply` 트리)의 각 앨범 폴더에 자체 완결형 `index.html`(같은 폴더 음원 재생 + 곡 정보 + 해설 패널)을 생성한다.

**Architecture:** M3-A가 `source_file.organized_path`에 기록한 복사 목적지를 앨범 폴더(`dirname`)별로 묶어, 의존성 0인 인라인 HTML/JS 플레이어 페이지를 폴더마다 쓴다. 로컬 LLM 없이 동작하며 해설 컬럼은 비워둔 채 슬롯만 마련한다(Phase 2가 채움).

**Tech Stack:** Python 3.11, stdlib만(`html`, `json`, `os`, `pathlib`), sqlite3, pytest. 새 런타임 의존성 없음.

## Global Constraints

- 원본 NTFS(`/mnt/win/memory/음악`)는 **읽기 전용** — 수정·이동·태그 재기록 금지. 페이지는 `/home`의 정리 트리에만 쓴다.
- 생성 HTML은 **자체 완결**: 외부 CDN/네트워크 참조 0(문자열에 `http://`/`https://` 등장 금지). `file://` 더블클릭으로 동작.
- 오디오는 `<audio src="상대 파일명">`로만 참조(인라인 `fetch` 사용 금지 — `file://` 제약). src는 JS `encodeURIComponent`로 인코딩.
- 사용자 텍스트(아티스트·앨범·곡·해설)는 모두 `html.escape`. UI 텍스트는 한국어.
- 모든 동작은 **멱등**(재실행 안전). 페이지는 파생물이라 항상 덮어쓴다.
- 테스트는 **헤르메틱**: 실제 라이브러리·네트워크 비의존, `:memory:` 또는 `tmp_path`만 사용.
- 기존 패턴 준수: 비파괴 마이그레이션(`ALTER TABLE ADD COLUMN`), dataclass Row, `from __future__ import annotations`.

---

## File Structure

- **Modify** `src/music_wiki/core/store.py` — `_migrate`에 `description`/`description_source` 컬럼, `AlbumRow`에 두 필드 + `albums_for_artist` SELECT, 새 `OrganizedRow` + `iter_organized()`, 새 `set_album_description()`.
- **Create** `src/music_wiki/organize/pages.py` — `render_album_html()`(순수) + `_track_label()` + `build_library_pages()`.
- **Modify** `src/music_wiki/cli.py` — `build-pages` 서브커맨드, `organize --apply` 후 페이지 자동 생성.
- **Create** `tests/test_store_pages.py`, `tests/test_pages.py`, `tests/test_cli_pages.py`.

---

## Task 1: store — 해설 컬럼 + AlbumRow + set_album_description

**Files:**
- Modify: `src/music_wiki/core/store.py` (`_migrate` 90-98, `AlbumRow` 40-53, `albums_for_artist` 189-199; 새 메서드는 `set_album_genre` 근처)
- Test: `tests/test_store_pages.py`

**Interfaces:**
- Consumes: `Store`, `AlbumRow`, `albums_for_artist(artist_id) -> list[AlbumRow]`, `iter_artists()`, `set_album_genre(...)` (기존).
- Produces:
  - `AlbumRow` 필드 추가: `description: str | None`, `description_source: str | None` (genre_source 다음).
  - `Store.set_album_description(self, album_id: int, description: str, source: str) -> None`.
  - `album` 테이블 컬럼 `description TEXT`, `description_source TEXT`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_store_pages.py`:

```python
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def _rec(path, hash_, artist="이문세", album="3집", title="소녀",
         track_no=7, disc_no=1):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=track_no,
        disc_no=disc_no, year=1987, label=None, genres=["Ballad"], duration_s=215.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_album_description_defaults_none_and_set():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description is None and album.description_source is None
    s.set_album_description(album.id, "잔잔한 발라드 명반.", "llm:qwen3-14b")
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description == "잔잔한 발라드 명반."
    assert album.description_source == "llm:qwen3-14b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store_pages.py::test_album_description_defaults_none_and_set -v`
Expected: FAIL — `AttributeError: 'AlbumRow' object has no attribute 'description'` (또는 `set_album_description` 없음).

- [ ] **Step 3: Implement**

In `src/music_wiki/core/store.py`, extend the migration loop (currently 92-95):

```python
        for col, decl in (("genre_bucket", "TEXT"), ("genre_confidence", "REAL"),
                          ("genre_source", "TEXT"), ("description", "TEXT"),
                          ("description_source", "TEXT")):
            if col not in album_cols:
                self.conn.execute(f"ALTER TABLE album ADD COLUMN {col} {decl}")
```

Add two fields to `AlbumRow` (after `genre_source`):

```python
@dataclass
class AlbumRow:
    id: int
    title: str
    year: int | None
    label: str | None
    genres: list[str]
    has_digital: bool
    has_vinyl: bool
    cover_path: str | None
    genre_bucket: str | None
    genre_confidence: float | None
    genre_source: str | None
    description: str | None
    description_source: str | None
```

Update `albums_for_artist` SELECT + row mapping:

```python
    def albums_for_artist(self, artist_id: int) -> list[AlbumRow]:
        cur = self.conn.execute(
            "SELECT id, title, year, label, genres, has_digital, has_vinyl, cover_path,"
            " genre_bucket, genre_confidence, genre_source, description,"
            " description_source"
            " FROM album WHERE artist_id=? ORDER BY year, title", (artist_id,)
        )
        return [
            AlbumRow(r[0], r[1], r[2], r[3], json.loads(r[4]), bool(r[5]), bool(r[6]),
                     r[7], r[8], r[9], r[10], r[11], r[12])
            for r in cur.fetchall()
        ]
```

Add the writer next to `set_album_genre`:

```python
    def set_album_description(self, album_id: int, description: str,
                              source: str) -> None:
        self.conn.execute(
            "UPDATE album SET description=?, description_source=? WHERE id=?",
            (description, source, album_id)
        )
        self.conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_store_pages.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite (no regressions in AlbumRow consumers)**

Run: `pytest -q`
Expected: all pass (existing `albums_for_artist` consumers — wiki, enrich — still work since fields are appended).

- [ ] **Step 6: Commit**

```bash
git add src/music_wiki/core/store.py tests/test_store_pages.py
git commit -m "feat: album description columns + set_album_description"
```

---

## Task 2: store — iter_organized + OrganizedRow

**Files:**
- Modify: `src/music_wiki/core/store.py` (새 `OrganizedRow` dataclass는 `OrganizeRow` 근처 56-65; `iter_organized` 메서드는 `iter_organizable` 261-272 근처)
- Test: `tests/test_store_pages.py`

**Interfaces:**
- Consumes: `set_organized_path(abs_path, organized_path)`, `set_album_genre(...)`, `set_album_description(...)` (Task 1), `iter_artists()`, `albums_for_artist(...)`.
- Produces:
  - `OrganizedRow` dataclass with fields (in this order): `organized_path: str`, `artist_name: str`, `album_title: str`, `album_year: int | None`, `genre_bucket: str | None`, `description: str | None`, `description_source: str | None`, `disc_no: int | None`, `track_no: int | None`, `track_title: str`, `duration_s: float | None`.
  - `Store.iter_organized(self) -> list[OrganizedRow]` — non-DRM source_files with non-NULL `organized_path`, joined to track/album/artist, ordered by artist, album, disc_no, track_no.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store_pages.py`:

```python
def test_iter_organized_groups_and_carries_metadata():
    s = _store()
    s.upsert(_rec("/src/7.mp3", "h1", title="소녀", track_no=7))
    s.upsert(_rec("/src/8.mp3", "h2", title="그늘", track_no=8))
    assert s.iter_organized() == []  # nothing organized yet
    s.set_organized_path("/src/7.mp3", "/lib/가요/이문세/3집/1-07 - 소녀.mp3")
    s.set_organized_path("/src/8.mp3", "/lib/가요/이문세/3집/1-08 - 그늘.mp3")
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "가요", 0.9, "rule")
    s.set_album_description(album.id, "해설입니다.", "llm:x")
    rows = s.iter_organized()
    assert len(rows) == 2
    r = rows[0]
    assert r.artist_name == "이문세" and r.album_title == "3집"
    assert r.album_year == 1987 and r.genre_bucket == "가요"
    assert r.description == "해설입니다." and r.duration_s == 215.0
    assert {x.track_no for x in rows} == {7, 8}


def test_iter_organized_excludes_drm_and_unorganized():
    s = _store()
    s.upsert(_rec("/src/7.mp3", "h1"))  # organized_path stays NULL
    s.record_drm(SourceFile(abs_path="/src/a.enc", content_hash="d1", mtime=1.0,
                            fmt="enc", is_drm=True))
    assert s.iter_organized() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store_pages.py::test_iter_organized_groups_and_carries_metadata -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'iter_organized'`.

- [ ] **Step 3: Implement**

In `src/music_wiki/core/store.py`, add the dataclass after `OrganizeRow`:

```python
@dataclass
class OrganizedRow:
    organized_path: str
    artist_name: str
    album_title: str
    album_year: int | None
    genre_bucket: str | None
    description: str | None
    description_source: str | None
    disc_no: int | None
    track_no: int | None
    track_title: str
    duration_s: float | None
```

Add the read method near `iter_organizable`:

```python
    def iter_organized(self) -> list[OrganizedRow]:
        cur = self.conn.execute(
            "SELECT sf.organized_path, ar.name, al.title, al.year, al.genre_bucket,"
            " al.description, al.description_source,"
            " t.disc_no, t.track_no, t.title, t.duration_s"
            " FROM source_file sf"
            " JOIN track t ON sf.track_id = t.id"
            " JOIN album al ON t.album_id = al.id"
            " JOIN artist ar ON al.artist_id = ar.id"
            " WHERE sf.organized_path IS NOT NULL AND sf.is_drm = 0"
            " ORDER BY ar.name, al.title, t.disc_no, t.track_no"
        )
        return [OrganizedRow(*r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_store_pages.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/store.py tests/test_store_pages.py
git commit -m "feat: Store.iter_organized for album-folder grouping"
```

---

## Task 3: pages — render_album_html (순수 함수)

**Files:**
- Create: `src/music_wiki/organize/pages.py`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: nothing (pure; stdlib `html`, `json`).
- Produces:
  - `render_album_html(*, artist: str, album: str, year: int | None, bucket: str | None, description: str | None, tracks: list[dict]) -> str`.
    `tracks[i]` keys: `"src"` (on-disk basename, str), `"label"` (str), `"duration_s"` (float | None).
    Returns a complete self-contained HTML document string.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pages.py`:

```python
from music_wiki.organize.pages import render_album_html


def _tracks():
    return [
        {"src": "1-07 - 소녀.mp3", "label": "1-07 소녀", "duration_s": 215.0},
        {"src": "1-08 - A & B.mp3", "label": "1-08 A & B", "duration_s": None},
    ]


def test_render_escapes_and_inlines_audio():
    page = render_album_html(artist="AC/DC", album="Back & Black", year=1980,
                             bucket="팝", description=None, tracks=_tracks())
    assert "<!doctype html>" in page.lower()
    assert "Back &amp; Black" in page          # album text escaped
    assert 'id="player"' in page               # single audio element
    assert "1-08 A &amp; B" in page            # playlist label escaped
    assert "1-08 - A & B.mp3" in page          # raw filename inlined for JS
    assert "encodeURIComponent" in page        # src encoded at click time
    assert "http://" not in page and "https://" not in page   # no network refs


def test_render_includes_description_when_present():
    page = render_album_html(artist="이문세", album="3집", year=1987, bucket="가요",
                             description="잔잔한 발라드.", tracks=_tracks())
    assert "해설" in page and "잔잔한 발라드." in page
    assert "AI 생성" in page


def test_render_omits_description_section_when_absent():
    page = render_album_html(artist="이문세", album="3집", year=1987, bucket="가요",
                             description=None, tracks=_tracks())
    assert "해설" not in page
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'music_wiki.organize.pages'`.

- [ ] **Step 3: Implement**

Create `src/music_wiki/organize/pages.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pages.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/pages.py tests/test_pages.py
git commit -m "feat: render_album_html self-contained album player page"
```

---

## Task 4: pages — build_library_pages

**Files:**
- Modify: `src/music_wiki/organize/pages.py` (add `_track_label`, `build_library_pages`)
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `Store.iter_organized() -> list[OrganizedRow]` (Task 2), `render_album_html(...)` (Task 3).
- Produces:
  - `build_library_pages(store: Store, *, dry_run: bool = False) -> int` — groups organized rows by `os.path.dirname(organized_path)`; for each existing folder writes `index.html`; returns number of album pages written (or, in dry_run, would-write count; folders that don't exist on disk are skipped and NOT counted). Idempotent (overwrites).
  - `_track_label(disc_no: int | None, track_no: int | None, title: str) -> str` — `"1-07 소녀"` / `"07 소녀"` / `title`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pages.py`:

```python
from pathlib import Path

from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.pages import build_library_pages


def _rec(path, hash_, title="소녀", track_no=7):
    return TrackRecord(
        artist_name="이문세", album_title="3집", track_title=title, track_no=track_no,
        disc_no=1, year=1987, label=None, genres=["Ballad"], duration_s=215.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _seed_two_track_album(tmp_path: Path) -> tuple[Store, Path]:
    folder = tmp_path / "가요" / "이문세" / "3집"
    folder.mkdir(parents=True)
    (folder / "1-07 - 소녀.mp3").write_bytes(b"a")
    (folder / "1-08 - 그늘.mp3").write_bytes(b"b")
    s = Store.open(":memory:")
    s.init_schema()
    s.upsert(_rec("/src/7.mp3", "h1", title="소녀", track_no=7))
    s.upsert(_rec("/src/8.mp3", "h2", title="그늘", track_no=8))
    s.set_organized_path("/src/7.mp3", str(folder / "1-07 - 소녀.mp3"))
    s.set_organized_path("/src/8.mp3", str(folder / "1-08 - 그늘.mp3"))
    return s, folder


def test_build_pages_writes_one_index_per_album(tmp_path):
    s, folder = _seed_two_track_album(tmp_path)
    assert build_library_pages(s) == 1
    page = (folder / "index.html").read_text(encoding="utf-8")
    assert "이문세 — 3집" in page
    assert "소녀" in page and "그늘" in page


def test_build_pages_dry_run_writes_nothing(tmp_path):
    s, folder = _seed_two_track_album(tmp_path)
    assert build_library_pages(s, dry_run=True) == 1
    assert not (folder / "index.html").exists()


def test_build_pages_skips_folder_not_on_disk(tmp_path):
    s = Store.open(":memory:")
    s.init_schema()
    s.upsert(_rec("/src/7.mp3", "h1"))
    s.set_organized_path("/src/7.mp3", "/nope/가요/이문세/3집/1-07 - 소녀.mp3")
    assert build_library_pages(s) == 0


def test_build_pages_idempotent(tmp_path):
    s, folder = _seed_two_track_album(tmp_path)
    build_library_pages(s)
    first = (folder / "index.html").read_text(encoding="utf-8")
    assert build_library_pages(s) == 1
    assert (folder / "index.html").read_text(encoding="utf-8") == first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pages.py::test_build_pages_writes_one_index_per_album -v`
Expected: FAIL — `ImportError: cannot import name 'build_library_pages'`.

- [ ] **Step 3: Implement**

In `src/music_wiki/organize/pages.py`, add `import os` and `from pathlib import Path` at top, then add:

```python
from music_wiki.core.store import Store


def _track_label(disc_no: int | None, track_no: int | None, title: str) -> str:
    if track_no is None:
        return title
    num = f"{disc_no}-{track_no:02d}" if disc_no is not None else f"{track_no:02d}"
    return f"{num} {title}"


def build_library_pages(store: Store, *, dry_run: bool = False) -> int:
    groups: dict[str, list] = {}
    order: list[str] = []
    for r in store.iter_organized():
        folder = os.path.dirname(r.organized_path)
        if folder not in groups:
            groups[folder] = []
            order.append(folder)
        groups[folder].append(r)

    written = 0
    for folder in order:
        if not os.path.isdir(folder):
            continue  # not materialized (e.g. dry-run organize) → skip, don't count
        rows = groups[folder]
        head = rows[0]
        tracks = [
            {
                "src": os.path.basename(r.organized_path),
                "label": _track_label(r.disc_no, r.track_no, r.track_title),
                "duration_s": r.duration_s,
            }
            for r in rows
        ]
        page = render_album_html(
            artist=head.artist_name, album=head.album_title, year=head.album_year,
            bucket=head.genre_bucket, description=head.description, tracks=tracks,
        )
        if not dry_run:
            Path(folder, "index.html").write_text(page, encoding="utf-8")
        written += 1
    return written
```

Top of file imports become:

```python
from __future__ import annotations

import html
import json
import os
from pathlib import Path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pages.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/pages.py tests/test_pages.py
git commit -m "feat: build_library_pages writes index.html per album folder"
```

---

## Task 5: CLI — build-pages 명령 + organize --apply 자동 생성

**Files:**
- Modify: `src/music_wiki/cli.py` (imports 13-18, `_cmd_organize` 69-80, `main` 파서 등록)
- Test: `tests/test_cli_pages.py`

**Interfaces:**
- Consumes: `build_library_pages(store, *, dry_run=False)` (Task 4), 기존 `_store_at`, `build_plan`, `run_plan`.
- Produces:
  - 새 서브커맨드 `build-pages` (`--db`, `--dry-run`) → `_cmd_build_pages`.
  - `organize --apply` 성공 후 `build_library_pages(store)` 호출, 출력에 `pages=N` 추가.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_pages.py`:

```python
from pathlib import Path

from music_wiki.cli import main
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def _seed_db(db_path: Path, src_file: Path):
    s = Store.open(str(db_path))
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="Bill Evans", album_title="Waltz", track_title="T", track_no=1,
        disc_no=None, year=1961, label=None, genres=["Jazz"], duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=str(src_file), content_hash="h1", mtime=1.0,
                          fmt="mp3"),
    ))


def test_organize_apply_generates_album_page(tmp_path: Path):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"audio")
    db = tmp_path / "wiki.db"
    target = tmp_path / "lib"
    _seed_db(db, src)

    assert main(["classify", "--db", str(db)]) == 0
    assert main(["organize", "--db", str(db), "--target", str(target),
                 "--apply"]) == 0
    page = target / "재즈" / "Bill Evans" / "Waltz" / "index.html"
    assert page.exists()
    assert "Bill Evans — Waltz" in page.read_text(encoding="utf-8")


def test_build_pages_command_rerenders(tmp_path: Path):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"audio")
    db = tmp_path / "wiki.db"
    target = tmp_path / "lib"
    _seed_db(db, src)
    main(["classify", "--db", str(db)])
    main(["organize", "--db", str(db), "--target", str(target), "--apply"])
    page = target / "재즈" / "Bill Evans" / "Waltz" / "index.html"
    page.unlink()  # remove, then rebuild via standalone command
    assert main(["build-pages", "--db", str(db)]) == 0
    assert page.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_pages.py -v`
Expected: FAIL — `test_organize_apply_generates_album_page` fails (no `index.html`); `test_build_pages_command_rerenders` fails with `argument cmd: invalid choice: 'build-pages'`.

- [ ] **Step 3: Implement**

In `src/music_wiki/cli.py`, add the import (near line 16):

```python
from music_wiki.organize.pages import build_library_pages
```

Replace `_cmd_organize` (69-80) so `--apply` also generates pages:

```python
def _cmd_organize(args) -> int:
    store = _store_at(args.db)
    ops = build_plan(store, args.target)
    stats = run_plan(ops, store, dry_run=not args.apply)
    if args.apply:
        pages = build_library_pages(store)
        print(f"[APPLIED] planned={stats.planned} copied={stats.copied} "
              f"skipped={stats.skipped} errors={stats.errors} pages={pages}")
    else:
        would = stats.planned - stats.skipped - stats.errors
        print(f"[DRY-RUN] planned={stats.planned} would_copy={would} "
              f"already={stats.skipped} target={args.target}  (use --apply to copy)")
    return 0
```

Add the command handler (after `_cmd_organize`):

```python
def _cmd_build_pages(args) -> int:
    store = _store_at(args.db)
    n = build_library_pages(store, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[DRY-RUN] would write {n} album pages")
    else:
        print(f"wrote {n} album index.html pages")
    return 0
```

Register the subparser in `main` (after the `organize` parser, before `args = parser.parse_args`):

```python
    p_pages = sub.add_parser("build-pages", help="앨범 폴더에 index.html (재)생성")
    p_pages.add_argument("--db", default=str(cfg.db_path))
    p_pages.add_argument("--dry-run", action="store_true")
    p_pages.set_defaults(func=_cmd_build_pages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_pages.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Run full suite + lint**

Run: `pytest -q && ruff check src tests`
Expected: all tests pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/music_wiki/cli.py tests/test_cli_pages.py
git commit -m "feat: build-pages CLI + auto-generate album pages on organize --apply"
```

---

## Self-Review (완료)

**Spec coverage:** §4.1(컬럼·AlbumRow·iter_organized·set_album_description)→Task 1,2 / §4.2 build_library_pages→Task 4 / §4.3 index.html(인라인 플레이어·해설·이스케이프·DRM 제외)→Task 3,4(DRM은 iter_organized의 `is_drm=0`으로 자동 제외, v1 카운트 표기는 생략 — 비목표 처리) / §4.4 CLI(build-pages + organize 자동연결)→Task 5. §8 안전·멱등·file:// 제약→Global Constraints + Task 3,4 테스트.

**Placeholder scan:** 모든 step에 실제 코드/명령/기대출력 포함. "적절한 처리" 류 표현 없음.

**Type consistency:** `OrganizedRow` 필드 순서 = `iter_organized` SELECT 열 순서 = `OrganizedRow(*r)` 매핑 일치. `render_album_html` 키(`src`/`label`/`duration_s`) = `build_library_pages`가 만드는 dict 키 일치. `build_library_pages(store, *, dry_run)` 시그니처 = CLI 호출부 일치. `set_album_description(album_id, description, source)` = Task 1 정의와 Task 2 테스트 사용 일치.
