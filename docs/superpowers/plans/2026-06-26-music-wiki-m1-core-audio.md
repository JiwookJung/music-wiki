# music-wiki M1 (core + audio) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the read-only music library into a SQLite knowledge base and a browsable markdown `[[wiki]]`, with Korean tag-encoding recovery and tag-first/folder-fallback entity resolution.

**Architecture:** A `core` package owns the data model, SQLite store (single source of truth), tag reading, encoding recovery, normalization, entity resolution, and the DB→markdown generator. `ingest/audio` walks the read-only source tree and drives the per-file pipeline; the markdown wiki is a regenerable output of the DB. External modules depend only on `core` interfaces.

**Tech Stack:** Python 3.11, `mutagen` (tags), stdlib `sqlite3`, `argparse`, `pytest`, `ruff`. `src/` package layout, editable install.

## Global Constraints

Copied verbatim from `docs/superpowers/specs/2026-06-26-music-wiki-design.md`. Every task implicitly includes these.

- Python 3.11 (matches CI).
- The original library at `/mnt/win/memory/음악` is **read-only — never modify, move, or re-tag source files**. All output goes to ext4 `/home`.
- SQLite is the single source of truth; the markdown wiki is a regenerable output (any run can rebuild it).
- Wiki output goes to a **separate, regenerable vault directory** (default `~/music-wiki-vault/`), never into the user's existing `~/Obsidian Vault`.
- Entity resolution is **tag-first, folder-path fallback**.
- Korean ID3 tags are often CP949/EUC-KR stored but Latin-1 labelled → decode with explicit recovery.
- Re-runs are **idempotent**, keyed by a cheap per-file signature (path + size + mtime); changed files re-upsert.
- `.enc` (Melon DRM) files are recorded as `is_drm`, never decoded; the wiki marks them "DRM, 재생불가".
- LLM summaries default to model `claude-opus-4-8` (the summary module is deferred to a follow-up plan; M1 does not call any LLM).

**M1 intentional simplifications (documented deviations from the spec's full model):**
- `label` and `genres` are stored as text columns on `album` (not normalized `label`/`genre`/`album_genre` tables). Normalizing for "browse by genre/label" is deferred until that query is actually needed (spec's own YAGNI stance).
- Embedded cover-art extraction is deferred; M1 records a **loose** cover image (`cover.*`/`folder.*`) found in the track's directory.
- `ffprobe` fallback for tag reading is deferred; M1 uses `mutagen` only.
- MusicBrainz enrichment (`--enrich`) and LLM summaries (`--summarize`) are deferred to a follow-up plan.

## File Structure

```
pyproject.toml                              # metadata, console script, ruff config
requirements.txt                            # mutagen
.github/workflows/ci.yml                    # MODIFY: install package, strict ruff
src/music_wiki/__init__.py
src/music_wiki/cli.py                       # `scan`, `build-wiki` entry points
src/music_wiki/core/__init__.py
src/music_wiki/core/config.py               # Config dataclass + defaults
src/music_wiki/core/models.py               # RawTags, TrackRecord, SourceFile, row dataclasses
src/music_wiki/core/encoding.py             # CP949/EUC-KR mojibake recovery
src/music_wiki/core/normalize.py            # name normalization, feat. splitting
src/music_wiki/core/store.py                # SQLite schema + upsert + queries (SSOT)
src/music_wiki/core/tags.py                 # TagReader protocol + MutagenTagReader
src/music_wiki/core/resolver.py             # EntityResolver: (RawTags, path) -> TrackRecord
src/music_wiki/core/art.py                  # find loose cover image in a directory
src/music_wiki/core/wiki.py                 # DB -> markdown generator
src/music_wiki/ingest/__init__.py
src/music_wiki/ingest/audio/__init__.py
src/music_wiki/ingest/audio/scan.py         # walk source tree, drive pipeline
tests/conftest.py
tests/test_encoding.py
tests/test_normalize.py
tests/test_store.py
tests/test_tags.py
tests/test_resolver.py
tests/test_art.py
tests/test_wiki.py
tests/test_scan.py
tests/test_cli.py
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `src/music_wiki/__init__.py`, `src/music_wiki/core/__init__.py`, `src/music_wiki/ingest/__init__.py`, `src/music_wiki/ingest/audio/__init__.py`, `src/music_wiki/core/config.py`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `music_wiki.core.config.Config(source_dir: Path, vault_dir: Path, db_path: Path, summary_model: str)`, classmethod `Config.default() -> Config`.

- [ ] **Step 1: Create the package skeleton and packaging files**

`pyproject.toml`:
```toml
[project]
name = "music-wiki"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["mutagen>=1.47"]

[project.scripts]
music-wiki = "music_wiki.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

`requirements.txt`:
```
mutagen>=1.47
```

Create these empty files: `src/music_wiki/__init__.py`, `src/music_wiki/core/__init__.py`, `src/music_wiki/ingest/__init__.py`, `src/music_wiki/ingest/audio/__init__.py`.

- [ ] **Step 2: Write the failing test for Config**

`tests/test_config.py`:
```python
from pathlib import Path
from music_wiki.core.config import Config


def test_default_config_paths():
    cfg = Config.default()
    assert cfg.source_dir == Path("/mnt/win/memory/음악")
    assert cfg.vault_dir == Path.home() / "music-wiki-vault"
    assert cfg.db_path == cfg.vault_dir / "music-wiki.db"
    assert cfg.summary_model == "claude-opus-4-8"
```

`tests/conftest.py`:
```python
# Shared fixtures live here; empty for now.
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pip install -e . && pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.core.config'`

- [ ] **Step 4: Implement Config**

`src/music_wiki/core/config.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    source_dir: Path
    vault_dir: Path
    db_path: Path
    summary_model: str = "claude-opus-4-8"

    @classmethod
    def default(cls) -> "Config":
        vault = Path.home() / "music-wiki-vault"
        return cls(
            source_dir=Path("/mnt/win/memory/음악"),
            vault_dir=vault,
            db_path=vault / "music-wiki.db",
        )
```

- [ ] **Step 5: Run the test and update CI**

Run: `pytest tests/test_config.py -v`
Expected: PASS

Modify `.github/workflows/ci.yml` — replace the "Install deps" and "Lint" steps so the package installs and ruff is strict:
```yaml
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -e .
          pip install ruff pytest
      - name: Lint (ruff)
        run: ruff check .
      - name: Test (pytest)
        run: pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt src/music_wiki tests/test_config.py tests/conftest.py .github/workflows/ci.yml
git commit -m "feat: scaffold music_wiki package, config, strict CI"
```

---

### Task 2: Data models

**Files:**
- Create: `src/music_wiki/core/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `RawTags(artist, album, title, track_no, disc_no, year, genre, label, duration_s, album_artist)` — all `Optional`, produced by `TagReader`.
  - `SourceFile(abs_path: str, content_hash: str, mtime: float, fmt: str, is_drm: bool=False, decode_status: str="ok")`.
  - `TrackRecord(artist_name, album_title, track_title, track_no, disc_no, year, label, genres: list[str], duration_s, cover_path: Optional[str], source: SourceFile)` — produced by `EntityResolver`, consumed by `Store.upsert`.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from music_wiki.core.models import RawTags, SourceFile, TrackRecord


def test_rawtags_defaults_to_none():
    t = RawTags()
    assert t.artist is None and t.duration_s is None


def test_trackrecord_holds_source_and_genres():
    src = SourceFile(abs_path="/x/a.mp3", content_hash="h", mtime=1.0, fmt="mp3")
    rec = TrackRecord(
        artist_name="IU", album_title="Lilac", track_title="Lilac",
        track_no=1, disc_no=None, year=2021, label=None, genres=["K-Pop"],
        duration_s=180.0, cover_path=None, source=src,
    )
    assert rec.source.fmt == "mp3"
    assert rec.genres == ["K-Pop"]
    assert src.decode_status == "ok" and src.is_drm is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.core.models'`

- [ ] **Step 3: Implement the models**

`src/music_wiki/core/models.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawTags:
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_no: int | None = None
    disc_no: int | None = None
    year: int | None = None
    genre: str | None = None
    label: str | None = None
    duration_s: float | None = None
    album_artist: str | None = None


@dataclass
class SourceFile:
    abs_path: str
    content_hash: str
    mtime: float
    fmt: str
    is_drm: bool = False
    decode_status: str = "ok"


@dataclass
class TrackRecord:
    artist_name: str
    album_title: str
    track_title: str
    track_no: int | None
    disc_no: int | None
    year: int | None
    label: str | None
    genres: list[str] = field(default_factory=list)
    duration_s: float | None = None
    cover_path: str | None = None
    source: SourceFile | None = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/models.py tests/test_models.py
git commit -m "feat: core data models (RawTags, SourceFile, TrackRecord)"
```

---

### Task 3: Encoding recovery

**Files:**
- Create: `src/music_wiki/core/encoding.py`
- Test: `tests/test_encoding.py`

**Interfaces:**
- Produces: `recover_text(s: Optional[str]) -> Optional[str]` — repairs CP949/EUC-KR text mis-decoded as Latin-1; returns input unchanged when it isn't mojibake.

- [ ] **Step 1: Write the failing tests**

`tests/test_encoding.py`:
```python
from music_wiki.core.encoding import recover_text


def _mojibake(korean: str) -> str:
    # Simulate cp949 bytes mis-decoded as latin-1 (the exact mutagen failure mode).
    return korean.encode("cp949").decode("latin-1")


def test_recovers_korean_mojibake():
    assert recover_text(_mojibake("아이유")) == "아이유"
    assert recover_text(_mojibake("좋은 날")) == "좋은 날"


def test_leaves_ascii_untouched():
    assert recover_text("Lilac") == "Lilac"


def test_leaves_clean_korean_untouched():
    assert recover_text("아이유") == "아이유"


def test_handles_none_and_empty():
    assert recover_text(None) is None
    assert recover_text("") == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_encoding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.core.encoding'`

- [ ] **Step 3: Implement recovery**

`src/music_wiki/core/encoding.py`:
```python
from __future__ import annotations


def _cjk_score(s: str) -> int:
    """Reward Hangul/CJK characters, penalize replacement chars."""
    score = 0
    for ch in s:
        if "가" <= ch <= "힣" or "一" <= ch <= "鿿":
            score += 1
        elif ch == "�":
            score -= 1
    return score


def recover_text(s: str | None) -> str | None:
    if not s:
        return s
    if s.isascii():
        return s
    try:
        candidate = s.encode("latin-1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    return candidate if _cjk_score(candidate) > _cjk_score(s) else s
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_encoding.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/encoding.py tests/test_encoding.py
git commit -m "feat: CP949/EUC-KR mojibake recovery"
```

---

### Task 4: Name normalization

**Files:**
- Create: `src/music_wiki/core/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces:
  - `clean_name(s: Optional[str]) -> Optional[str]` — trims and collapses internal whitespace.
  - `match_key(s: str) -> str` — `clean_name` + casefold, used by the store for dedup.
  - `split_feat(title: str) -> tuple[str, list[str]]` — strips a trailing `(feat. …)` and returns `(clean_title, [featured_artists])`.

- [ ] **Step 1: Write the failing tests**

`tests/test_normalize.py`:
```python
from music_wiki.core.normalize import clean_name, match_key, split_feat


def test_clean_name_trims_and_collapses():
    assert clean_name("  IU   Official ") == "IU Official"
    assert clean_name(None) is None


def test_match_key_is_casefolded():
    assert match_key("The Beatles") == match_key("the beatles")


def test_split_feat_extracts_artists():
    assert split_feat("Lilac (feat. SUGA)") == ("Lilac", ["SUGA"])
    assert split_feat("Song [Feat. A & B]") == ("Song", ["A & B"])


def test_split_feat_passthrough_when_absent():
    assert split_feat("Plain Title") == ("Plain Title", [])
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement normalization**

`src/music_wiki/core/normalize.py`:
```python
from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_FEAT = re.compile(
    r"\s*[\(\[]\s*(?:feat\.?|featuring|with)\s+(.+?)\s*[\)\]]\s*$",
    re.IGNORECASE,
)


def clean_name(s: str | None) -> str | None:
    if s is None:
        return None
    return _WS.sub(" ", s).strip()


def match_key(s: str) -> str:
    return (clean_name(s) or "").casefold()


def split_feat(title: str) -> tuple[str, list[str]]:
    m = _FEAT.search(title)
    if not m:
        return clean_name(title) or title, []
    artists = [a.strip() for a in re.split(r",|&|/", m.group(1)) if a.strip()]
    clean = _FEAT.sub("", title)
    return clean_name(clean) or clean, artists
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_normalize.py -v`
Expected: PASS (4 tests). Note: `split_feat("Song [Feat. A & B]")` returns `["A & B"]`? It will split on `&` → `["A", "B"]`. **Fix the test expectation to `("Song", ["A", "B"])`** before running, since `&` is a separator.

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/normalize.py tests/test_normalize.py
git commit -m "feat: name normalization and feat. splitting"
```

---

### Task 5: SQLite store

**Files:**
- Create: `src/music_wiki/core/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `TrackRecord`, `SourceFile` (Task 2); `match_key` (Task 4).
- Produces:
  - `Store(conn: sqlite3.Connection)`, `Store.open(path) -> Store`, `Store.init_schema()`.
  - `Store.upsert(rec: TrackRecord) -> None` — idempotent on `rec.source.content_hash`; sets the album's `has_digital=1`.
  - `Store.record_drm(src: SourceFile) -> None`.
  - Query methods for the wiki: `iter_artists() -> list[ArtistRow]`, `albums_for_artist(artist_id) -> list[AlbumRow]`, `tracks_for_album(album_id) -> list[TrackRow]`.
  - Row types `ArtistRow(id, name)`, `AlbumRow(id, title, year, label, genres: list[str], has_digital, has_vinyl, cover_path)`, `TrackRow(id, title, disc_no, track_no, duration_s)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_store.py`:
```python
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def _rec(path, hash_, artist="IU", album="Lilac", title="Lilac", track_no=1):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title,
        track_no=track_no, disc_no=None, year=2021, label="EDAM",
        genres=["K-Pop"], duration_s=180.0, cover_path="/x/cover.jpg",
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_upsert_creates_artist_album_track():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    artists = s.iter_artists()
    assert [a.name for a in artists] == ["IU"]
    albums = s.albums_for_artist(artists[0].id)
    assert albums[0].title == "Lilac"
    assert albums[0].has_digital is True and albums[0].has_vinyl is False
    assert albums[0].genres == ["K-Pop"]
    tracks = s.tracks_for_album(albums[0].id)
    assert [t.title for t in tracks] == ["Lilac"]


def test_upsert_is_idempotent_on_content_hash():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    s.upsert(_rec("/x/1.mp3", "h1"))  # same file, second run
    assert len(s.tracks_for_album(s.albums_for_artist(s.iter_artists()[0].id)[0].id)) == 1


def test_dedup_artist_by_case_insensitive_key():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", artist="The Beatles"))
    s.upsert(_rec("/x/2.mp3", "h2", artist="the beatles", title="B", track_no=2))
    assert len(s.iter_artists()) == 1


def test_record_drm():
    s = _store()
    s.record_drm(SourceFile(abs_path="/x/a.enc", content_hash="d1", mtime=1.0,
                            fmt="enc", is_drm=True))
    assert s.drm_count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the store**

`src/music_wiki/core/store.py`:
```python
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .models import SourceFile, TrackRecord
from .normalize import match_key

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artist (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS album (
    id INTEGER PRIMARY KEY, artist_id INTEGER NOT NULL REFERENCES artist(id),
    title TEXT NOT NULL, title_key TEXT NOT NULL, year INTEGER, label TEXT,
    genres TEXT NOT NULL DEFAULT '[]', cover_path TEXT,
    has_digital INTEGER NOT NULL DEFAULT 0, has_vinyl INTEGER NOT NULL DEFAULT 0,
    UNIQUE(artist_id, title_key)
);
CREATE TABLE IF NOT EXISTS track (
    id INTEGER PRIMARY KEY, album_id INTEGER NOT NULL REFERENCES album(id),
    title TEXT NOT NULL, title_key TEXT NOT NULL, disc_no INTEGER, track_no INTEGER,
    duration_s REAL, UNIQUE(album_id, disc_no, track_no, title_key)
);
CREATE TABLE IF NOT EXISTS source_file (
    id INTEGER PRIMARY KEY, track_id INTEGER REFERENCES track(id),
    abs_path TEXT NOT NULL, content_hash TEXT NOT NULL UNIQUE, mtime REAL,
    fmt TEXT, decode_status TEXT, is_drm INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class ArtistRow:
    id: int
    name: str


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


@dataclass
class TrackRow:
    id: int
    title: str
    disc_no: int | None
    track_no: int | None
    duration_s: float | None


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def open(cls, path: str) -> "Store":
        return cls(sqlite3.connect(path))

    def init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- writes ---
    def _artist_id(self, name: str) -> int:
        key = match_key(name)
        cur = self.conn.execute("SELECT id FROM artist WHERE name_key=?", (key,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur = self.conn.execute(
            "INSERT INTO artist(name, name_key) VALUES(?, ?)", (name, key)
        )
        return cur.lastrowid

    def _album_id(self, artist_id: int, rec: TrackRecord) -> int:
        key = match_key(rec.album_title)
        cur = self.conn.execute(
            "SELECT id FROM album WHERE artist_id=? AND title_key=?", (artist_id, key)
        )
        row = cur.fetchone()
        if row:
            album_id = row[0]
        else:
            cur = self.conn.execute(
                "INSERT INTO album(artist_id, title, title_key, year, label, genres,"
                " cover_path, has_digital) VALUES(?,?,?,?,?,?,?,1)",
                (artist_id, rec.album_title, key, rec.year, rec.label,
                 json.dumps(rec.genres, ensure_ascii=False), rec.cover_path),
            )
            return cur.lastrowid
        # fill gaps + ensure has_digital
        self.conn.execute(
            "UPDATE album SET has_digital=1,"
            " year=COALESCE(year, ?), label=COALESCE(label, ?),"
            " cover_path=COALESCE(cover_path, ?) WHERE id=?",
            (rec.year, rec.label, rec.cover_path, album_id),
        )
        return album_id

    def _track_id(self, album_id: int, rec: TrackRecord) -> int:
        key = match_key(rec.track_title)
        cur = self.conn.execute(
            "SELECT id FROM track WHERE album_id=? AND IFNULL(disc_no,-1)=IFNULL(?,-1)"
            " AND IFNULL(track_no,-1)=IFNULL(?,-1) AND title_key=?",
            (album_id, rec.disc_no, rec.track_no, key),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur = self.conn.execute(
            "INSERT INTO track(album_id, title, title_key, disc_no, track_no,"
            " duration_s) VALUES(?,?,?,?,?,?)",
            (album_id, rec.track_title, key, rec.disc_no, rec.track_no, rec.duration_s),
        )
        return cur.lastrowid

    def upsert(self, rec: TrackRecord) -> None:
        artist_id = self._artist_id(rec.artist_name)
        album_id = self._album_id(artist_id, rec)
        track_id = self._track_id(album_id, rec)
        src = rec.source
        self.conn.execute(
            "INSERT INTO source_file(track_id, abs_path, content_hash, mtime, fmt,"
            " decode_status, is_drm) VALUES(?,?,?,?,?,?,0)"
            " ON CONFLICT(content_hash) DO UPDATE SET track_id=excluded.track_id,"
            " abs_path=excluded.abs_path, mtime=excluded.mtime,"
            " decode_status=excluded.decode_status",
            (track_id, src.abs_path, src.content_hash, src.mtime, src.fmt,
             src.decode_status),
        )
        self.conn.commit()

    def record_drm(self, src: SourceFile) -> None:
        self.conn.execute(
            "INSERT INTO source_file(abs_path, content_hash, mtime, fmt, is_drm)"
            " VALUES(?,?,?,?,1) ON CONFLICT(content_hash) DO NOTHING",
            (src.abs_path, src.content_hash, src.mtime, src.fmt),
        )
        self.conn.commit()

    def has_signature(self, content_hash: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM source_file WHERE content_hash=?", (content_hash,)
        )
        return cur.fetchone() is not None

    # --- reads ---
    def iter_artists(self) -> list[ArtistRow]:
        cur = self.conn.execute("SELECT id, name FROM artist ORDER BY name")
        return [ArtistRow(*r) for r in cur.fetchall()]

    def albums_for_artist(self, artist_id: int) -> list[AlbumRow]:
        cur = self.conn.execute(
            "SELECT id, title, year, label, genres, has_digital, has_vinyl, cover_path"
            " FROM album WHERE artist_id=? ORDER BY year, title", (artist_id,)
        )
        return [
            AlbumRow(r[0], r[1], r[2], r[3], json.loads(r[4]), bool(r[5]), bool(r[6]), r[7])
            for r in cur.fetchall()
        ]

    def tracks_for_album(self, album_id: int) -> list[TrackRow]:
        cur = self.conn.execute(
            "SELECT id, title, disc_no, track_no, duration_s FROM track"
            " WHERE album_id=? ORDER BY disc_no, track_no, title", (album_id,)
        )
        return [TrackRow(*r) for r in cur.fetchall()]

    def drm_count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM source_file WHERE is_drm=1")
        return cur.fetchone()[0]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/store.py tests/test_store.py
git commit -m "feat: SQLite store with idempotent upsert and wiki queries"
```

---

### Task 6: Tag reader

**Files:**
- Create: `src/music_wiki/core/tags.py`
- Test: `tests/test_tags.py`

**Interfaces:**
- Consumes: `RawTags` (Task 2); `recover_text` (Task 3).
- Produces:
  - `TagReader` Protocol with `read(self, path: str) -> RawTags`.
  - `MutagenTagReader(loader: Callable[[str], object] | None = None)` — default loader is `lambda p: mutagen.File(p, easy=True)`. Applies `recover_text` to artist/album/title/genre. Returns an all-`None` `RawTags` when the loader returns `None`.
  - `extract_tags(mf) -> RawTags` — pure function over a mutagen-`easy`-style mapping with `.info.length`.

- [ ] **Step 1: Write the failing tests (hermetic — no real mp3)**

`tests/test_tags.py`:
```python
from music_wiki.core.tags import MutagenTagReader, extract_tags


class _FakeInfo:
    length = 200.0


class _FakeFile(dict):
    """Mimics a mutagen easy File: dict of list-values + .info.length."""
    info = _FakeInfo()


def _mojibake(korean: str) -> str:
    return korean.encode("cp949").decode("latin-1")


def test_extract_reads_and_recovers():
    mf = _FakeFile({
        "artist": [_mojibake("아이유")],
        "album": ["Lilac"],
        "title": [_mojibake("좋은 날")],
        "tracknumber": ["3/12"],
        "date": ["2021"],
        "genre": ["K-Pop"],
    })
    t = extract_tags(mf)
    assert t.artist == "아이유"
    assert t.album == "Lilac"
    assert t.title == "좋은 날"
    assert t.track_no == 3
    assert t.year == 2021
    assert t.duration_s == 200.0


def test_reader_returns_empty_on_unreadable():
    reader = MutagenTagReader(loader=lambda p: None)
    assert extract_tags is not None  # sanity
    t = reader.read("/nope.mp3")
    assert t.artist is None and t.album is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_tags.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the tag reader**

`src/music_wiki/core/tags.py`:
```python
from __future__ import annotations

from typing import Callable, Protocol

from .encoding import recover_text
from .models import RawTags


class TagReader(Protocol):
    def read(self, path: str) -> RawTags: ...


def _first(mf, key: str) -> str | None:
    val = mf.get(key) if hasattr(mf, "get") else None
    if not val:
        return None
    return str(val[0]) if isinstance(val, (list, tuple)) else str(val)


def _to_int(s: str | None) -> int | None:
    if not s:
        return None
    head = s.split("/")[0].strip()
    return int(head) if head.isdigit() else None


def _year(s: str | None) -> int | None:
    if not s:
        return None
    digits = s[:4]
    return int(digits) if digits.isdigit() else None


def extract_tags(mf) -> RawTags:
    length = getattr(getattr(mf, "info", None), "length", None)
    return RawTags(
        artist=recover_text(_first(mf, "artist")),
        album=recover_text(_first(mf, "album")),
        title=recover_text(_first(mf, "title")),
        track_no=_to_int(_first(mf, "tracknumber")),
        disc_no=_to_int(_first(mf, "discnumber")),
        year=_year(_first(mf, "date") or _first(mf, "year")),
        genre=recover_text(_first(mf, "genre")),
        label=recover_text(_first(mf, "organization")),
        duration_s=float(length) if length is not None else None,
        album_artist=recover_text(_first(mf, "albumartist")),
    )


class MutagenTagReader:
    def __init__(self, loader: Callable[[str], object] | None = None):
        if loader is None:
            import mutagen

            loader = lambda p: mutagen.File(p, easy=True)  # noqa: E731
        self._loader = loader

    def read(self, path: str) -> RawTags:
        mf = self._loader(path)
        if mf is None:
            return RawTags()
        return extract_tags(mf)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_tags.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/tags.py tests/test_tags.py
git commit -m "feat: mutagen tag reader with encoding recovery (injectable loader)"
```

---

### Task 7: Entity resolver

**Files:**
- Create: `src/music_wiki/core/resolver.py`
- Test: `tests/test_resolver.py`

**Interfaces:**
- Consumes: `RawTags`, `SourceFile`, `TrackRecord` (Task 2); `clean_name`, `split_feat` (Task 4).
- Produces: `EntityResolver.resolve(tags: RawTags, path: str, source: SourceFile) -> TrackRecord`. Tag-first; when artist/album/title are missing, derive from the path: `<…>/<artist>/<album>/<NN title>.mp3`, and parse the flat `melon` pattern `아티스트-NN-제목.mp3`.

- [ ] **Step 1: Write the failing tests**

`tests/test_resolver.py`:
```python
from music_wiki.core.models import RawTags, SourceFile
from music_wiki.core.resolver import EntityResolver

SRC = SourceFile(abs_path="/x.mp3", content_hash="h", mtime=1.0, fmt="mp3")


def test_tag_first():
    tags = RawTags(artist="IU", album="Lilac", title="Lilac (feat. SUGA)", track_no=1)
    rec = EntityResolver().resolve(tags, "/lib/whatever.mp3", SRC)
    assert rec.artist_name == "IU"
    assert rec.album_title == "Lilac"
    assert rec.track_title == "Lilac"  # feat. stripped


def test_folder_fallback_when_tags_missing():
    tags = RawTags()
    path = "/mnt/win/memory/음악/Music/김동률/감사/02 출발.mp3"
    rec = EntityResolver().resolve(tags, path, SRC)
    assert rec.artist_name == "김동률"
    assert rec.album_title == "감사"
    assert rec.track_title == "출발"
    assert rec.track_no == 2


def test_melon_flat_pattern():
    tags = RawTags()
    path = "/mnt/win/memory/음악/melon/아이유-01-좋은 날.mp3"
    rec = EntityResolver().resolve(tags, path, SRC)
    assert rec.artist_name == "아이유"
    assert rec.track_title == "좋은 날"
    assert rec.track_no == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the resolver**

`src/music_wiki/core/resolver.py`:
```python
from __future__ import annotations

import re
from pathlib import PurePosixPath

from .models import RawTags, SourceFile, TrackRecord
from .normalize import clean_name, split_feat

_LEADING_NO = re.compile(r"^\s*(\d{1,3})[\s.\-_]+")
_MELON = re.compile(r"^(?P<artist>.+?)-(?P<no>\d{1,3})-(?P<title>.+)$")


def _strip_leading_no(stem: str) -> tuple[str, int | None]:
    m = _LEADING_NO.match(stem)
    if m:
        return stem[m.end():].strip(), int(m.group(1))
    return stem.strip(), None


class EntityResolver:
    def resolve(self, tags: RawTags, path: str, source: SourceFile) -> TrackRecord:
        p = PurePosixPath(path)
        stem = p.stem
        artist = clean_name(tags.album_artist) or clean_name(tags.artist)
        album = clean_name(tags.album)
        title = clean_name(tags.title)
        track_no = tags.track_no

        # melon flat pattern: artist-NN-title.mp3
        if (not artist or not title):
            m = _MELON.match(stem)
            if m:
                artist = artist or clean_name(m.group("artist"))
                title = title or clean_name(m.group("title"))
                track_no = track_no or int(m.group("no"))

        # folder fallback: <artist>/<album>/<NN title>.ext
        parts = p.parts
        if not title:
            t, n = _strip_leading_no(stem)
            title = t
            track_no = track_no or n
        if not album and len(parts) >= 2:
            album = clean_name(parts[-2])
        if not artist and len(parts) >= 3:
            artist = clean_name(parts[-3])

        title_clean, _feat = split_feat(title or stem)
        return TrackRecord(
            artist_name=artist or "Unknown Artist",
            album_title=album or "Unknown Album",
            track_title=title_clean or stem,
            track_no=track_no,
            disc_no=tags.disc_no,
            year=tags.year,
            label=tags.label,
            genres=[tags.genre] if tags.genre else [],
            duration_s=tags.duration_s,
            cover_path=None,
            source=source,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_resolver.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/resolver.py tests/test_resolver.py
git commit -m "feat: tag-first entity resolver with folder and melon fallbacks"
```

---

### Task 8: Loose cover art

**Files:**
- Create: `src/music_wiki/core/art.py`
- Test: `tests/test_art.py`

**Interfaces:**
- Produces: `find_cover(directory: str) -> Optional[str]` — returns the absolute path of a loose cover image (`cover.*`, `folder.*`, or the single image in the directory), else `None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_art.py`:
```python
from pathlib import Path
from music_wiki.core.art import find_cover


def test_prefers_cover_named_file(tmp_path: Path):
    (tmp_path / "track.mp3").write_bytes(b"x")
    (tmp_path / "random.jpg").write_bytes(b"x")
    (tmp_path / "cover.jpg").write_bytes(b"x")
    assert find_cover(str(tmp_path)) == str(tmp_path / "cover.jpg")


def test_falls_back_to_sole_image(tmp_path: Path):
    (tmp_path / "art.png").write_bytes(b"x")
    assert find_cover(str(tmp_path)) == str(tmp_path / "art.png")


def test_none_when_no_image(tmp_path: Path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    assert find_cover(str(tmp_path)) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_art.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement cover lookup**

`src/music_wiki/core/art.py`:
```python
from __future__ import annotations

from pathlib import Path

_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
_PREFERRED = ("cover", "folder", "front", "album")


def find_cover(directory: str) -> str | None:
    d = Path(directory)
    if not d.is_dir():
        return None
    images = sorted(
        p for p in d.iterdir() if p.is_file() and p.suffix.lower() in _IMG_EXT
    )
    if not images:
        return None
    for pref in _PREFERRED:
        for img in images:
            if img.stem.lower() == pref:
                return str(img)
    return str(images[0])
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_art.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/art.py tests/test_art.py
git commit -m "feat: loose cover-art lookup"
```

---

### Task 9: Wiki generator

**Files:**
- Create: `src/music_wiki/core/wiki.py`
- Test: `tests/test_wiki.py`

**Interfaces:**
- Consumes: `Store` and its row types (Task 5).
- Produces: `WikiGenerator(store: Store)`, `generate(out_dir: str) -> None` — writes `artists/<name>.md` and `albums/<artist> - <album>.md`. Artist pages list albums as `[[artist - album]]` links; album pages show ownership badges, year/label, cover, and a track table. Helper `safe_filename(name: str) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_wiki.py`:
```python
from pathlib import Path
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.core.wiki import WikiGenerator, safe_filename


def _seed(store):
    store.upsert(TrackRecord(
        artist_name="IU", album_title="Lilac", track_title="Lilac",
        track_no=1, disc_no=None, year=2021, label="EDAM", genres=["K-Pop"],
        duration_s=215.0, cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    ))


def test_safe_filename_strips_separators():
    assert safe_filename("AC/DC: Live") == "AC_DC_ Live"


def test_generate_writes_artist_and_album_pages(tmp_path: Path):
    s = Store.open(":memory:")
    s.init_schema()
    _seed(s)
    WikiGenerator(s).generate(str(tmp_path))
    artist_md = (tmp_path / "artists" / "IU.md").read_text(encoding="utf-8")
    assert "[[IU - Lilac]]" in artist_md
    album_md = (tmp_path / "albums" / "IU - Lilac.md").read_text(encoding="utf-8")
    assert "[[IU]]" in album_md
    assert "디지털 보유" in album_md
    assert "Lilac" in album_md and "2021" in album_md
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_wiki.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the generator**

`src/music_wiki/core/wiki.py`:
```python
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
                lines.append(f"- [[{artist.name} - {a.title}]]{year}")
        path = out / "artists" / f"{safe_filename(artist.name)}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_album(self, out: Path, artist, album) -> None:
        lines = [f"# {album.title}", "", f"아티스트: [[{artist.name}]]"]
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_wiki.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/wiki.py tests/test_wiki.py
git commit -m "feat: DB-to-markdown wiki generator with [[links]] and ownership badges"
```

---

### Task 10: Audio scan pipeline

**Files:**
- Create: `src/music_wiki/ingest/audio/scan.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: `Store` (Task 5), `TagReader`/`MutagenTagReader` (Task 6), `EntityResolver` (Task 7), `find_cover` (Task 8), `SourceFile` (Task 2).
- Produces:
  - `file_signature(path: str) -> tuple[str, float, int]` — `(content_hash, mtime, size)` where `content_hash = sha1("abs_path:size:int(mtime)")`.
  - `AUDIO_EXT: set[str]` and `DRM_EXT = {".enc"}`.
  - `scan_library(source_dir: str, store: Store, tag_reader: TagReader, *, skip_unchanged: bool = True) -> ScanStats`, with `ScanStats(scanned, ingested, drm, skipped)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_scan.py`:
```python
from pathlib import Path
from music_wiki.core.models import RawTags
from music_wiki.core.store import Store
from music_wiki.ingest.audio.scan import scan_library, file_signature


class FakeReader:
    """Returns tags based on filename so tests need no real mp3."""
    def read(self, path: str) -> RawTags:
        if "iu" in path.lower():
            return RawTags(artist="IU", album="Lilac", title="Lilac", track_no=1, year=2021)
        return RawTags()


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_ingests_audio_and_records_drm(tmp_path: Path):
    (tmp_path / "iu.mp3").write_bytes(b"audio")
    (tmp_path / "locked.enc").write_bytes(b"drm")
    (tmp_path / "notes.txt").write_bytes(b"ignore")
    s = _store()
    stats = scan_library(str(tmp_path), s, FakeReader())
    assert stats.ingested == 1
    assert stats.drm == 1
    assert s.iter_artists()[0].name == "IU"
    assert s.drm_count() == 1


def test_rerun_skips_unchanged(tmp_path: Path):
    (tmp_path / "iu.mp3").write_bytes(b"audio")
    s = _store()
    scan_library(str(tmp_path), s, FakeReader())
    stats2 = scan_library(str(tmp_path), s, FakeReader())
    assert stats2.skipped == 1 and stats2.ingested == 0


def test_signature_is_deterministic(tmp_path: Path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    assert file_signature(str(f))[0] == file_signature(str(f))[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_scan.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the scanner**

`src/music_wiki/ingest/audio/scan.py`:
```python
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from music_wiki.core.art import find_cover
from music_wiki.core.models import SourceFile
from music_wiki.core.resolver import EntityResolver
from music_wiki.core.store import Store
from music_wiki.core.tags import TagReader

AUDIO_EXT = {".mp3", ".flac", ".ape", ".ogg", ".wav", ".m4a", ".wma"}
DRM_EXT = {".enc"}


@dataclass
class ScanStats:
    scanned: int = 0
    ingested: int = 0
    drm: int = 0
    skipped: int = 0


def file_signature(path: str) -> tuple[str, float, int]:
    st = os.stat(path)
    raw = f"{os.path.abspath(path)}:{st.st_size}:{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest(), st.st_mtime, st.st_size


def scan_library(
    source_dir: str, store: Store, tag_reader: TagReader, *, skip_unchanged: bool = True
) -> ScanStats:
    stats = ScanStats()
    resolver = EntityResolver()
    for root, _dirs, files in os.walk(source_dir):
        for name in files:
            ext = Path(name).suffix.lower()
            full = os.path.join(root, name)
            if ext in DRM_EXT:
                sig, mtime, _size = file_signature(full)
                store.record_drm(SourceFile(abs_path=full, content_hash=sig,
                                            mtime=mtime, fmt=ext.lstrip("."), is_drm=True))
                stats.drm += 1
                continue
            if ext not in AUDIO_EXT:
                continue
            stats.scanned += 1
            sig, mtime, _size = file_signature(full)
            if skip_unchanged and store.has_signature(sig):
                stats.skipped += 1
                continue
            src = SourceFile(abs_path=full, content_hash=sig, mtime=mtime,
                             fmt=ext.lstrip("."))
            tags = tag_reader.read(full)
            rec = resolver.resolve(tags, full, src)
            rec.cover_path = find_cover(root)
            store.upsert(rec)
            stats.ingested += 1
    return stats
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_scan.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/ingest/audio/scan.py tests/test_scan.py
git commit -m "feat: audio scan pipeline (idempotent, DRM-aware)"
```

---

### Task 11: CLI

**Files:**
- Create: `src/music_wiki/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `Store` (Task 5), `MutagenTagReader` (Task 6), `scan_library` (Task 10), `WikiGenerator` (Task 9).
- Produces: `main(argv: list[str] | None = None) -> int` with subcommands `scan [--source DIR] [--db PATH]` and `build-wiki [--db PATH] [--out DIR]`.

- [ ] **Step 1: Write the failing test (end-to-end on a temp library)**

`tests/test_cli.py`:
```python
from pathlib import Path
from music_wiki.cli import main


def test_scan_then_build_wiki(tmp_path: Path, monkeypatch):
    # Build a fake library; stub the tag reader so no real mp3 is needed.
    lib = tmp_path / "lib"
    (lib / "IU" / "Lilac").mkdir(parents=True)
    (lib / "IU" / "Lilac" / "01 Lilac.mp3").write_bytes(b"audio")
    db = tmp_path / "wiki.db"
    out = tmp_path / "vault"

    from music_wiki.core.models import RawTags

    class FakeReader:
        def read(self, path):
            return RawTags(artist="IU", album="Lilac", title="Lilac", track_no=1, year=2021)

    monkeypatch.setattr("music_wiki.cli.MutagenTagReader", lambda: FakeReader())

    assert main(["scan", "--source", str(lib), "--db", str(db)]) == 0
    assert main(["build-wiki", "--db", str(db), "--out", str(out)]) == 0
    assert (out / "albums" / "IU - Lilac.md").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the CLI**

`src/music_wiki/cli.py`:
```python
from __future__ import annotations

import argparse
from pathlib import Path

from music_wiki.core.config import Config
from music_wiki.core.store import Store
from music_wiki.core.tags import MutagenTagReader
from music_wiki.core.wiki import WikiGenerator
from music_wiki.ingest.audio.scan import scan_library


def _store_at(db_path: str) -> Store:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store = Store.open(db_path)
    store.init_schema()
    return store


def _cmd_scan(args) -> int:
    store = _store_at(args.db)
    stats = scan_library(args.source, store, MutagenTagReader())
    print(f"scanned={stats.scanned} ingested={stats.ingested} "
          f"drm={stats.drm} skipped={stats.skipped}")
    return 0


def _cmd_build_wiki(args) -> int:
    store = _store_at(args.db)
    WikiGenerator(store).generate(args.out)
    print(f"wiki written to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    cfg = Config.default()
    parser = argparse.ArgumentParser(prog="music-wiki")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="스캔 → DB (멱등)")
    p_scan.add_argument("--source", default=str(cfg.source_dir))
    p_scan.add_argument("--db", default=str(cfg.db_path))
    p_scan.set_defaults(func=_cmd_scan)

    p_wiki = sub.add_parser("build-wiki", help="DB → 마크다운 위키")
    p_wiki.add_argument("--db", default=str(cfg.db_path))
    p_wiki.add_argument("--out", default=str(cfg.vault_dir))
    p_wiki.set_defaults(func=_cmd_build_wiki)

    args = parser.parse_args(argv)
    return args.func(args)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and lint**

Run: `pytest -q && ruff check .`
Expected: all tests PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/music_wiki/cli.py tests/test_cli.py
git commit -m "feat: CLI with scan and build-wiki commands"
```

---

### Task 12: Manual verification against the real library

**Files:** none (manual smoke test; read-only).

**Interfaces:** none.

- [ ] **Step 1: Scan a single real subtree (read-only, small)**

Run (uses the real `mutagen` path, a small folder to keep it fast):
```bash
music-wiki scan --source "/mnt/win/memory/음악/melon" --db /tmp/mw-smoke.db
```
Expected: prints `scanned=… ingested=… drm=… skipped=…` with `ingested > 0` and no traceback. Confirms real mutagen reads + encoding recovery on actual Korean tags.

- [ ] **Step 2: Build the wiki and eyeball it**

Run:
```bash
music-wiki build-wiki --db /tmp/mw-smoke.db --out /tmp/mw-vault
ls /tmp/mw-vault/albums | head
```
Expected: album/artist `.md` files exist; open one and confirm Korean names render correctly (no mojibake) and `[[links]]` + ownership badge are present.

- [ ] **Step 3: Confirm idempotency**

Run the same scan again:
```bash
music-wiki scan --source "/mnt/win/memory/음악/melon" --db /tmp/mw-smoke.db
```
Expected: `skipped` ≈ previous `ingested`, `ingested=0`.

- [ ] **Step 4: Record findings**

Note any folders where Korean names came out as mojibake or where resolution mis-grouped albums; these feed the M2 / enrichment backlog. No commit (scratch DB under `/tmp`).

---

## Self-Review

**1. Spec coverage:**
- §3 architecture (core / ingest.audio / cli) → Tasks 1–11. ✅
- §4 data model (artist/album/track/source_file, ownership flags, idempotency) → Task 5; label/genre as text columns is a documented M1 simplification (Global Constraints). ✅
- §5 audio pipeline: scan(1) → tags(2,3) → normalize(4) → resolve(5) → art(6→loose only, documented) → store(7) → wiki(10). MusicBrainz(8)/summary(9) deferred — documented. ✅
- §2 risks: encoding → Task 3; entity resolution → Task 7. ✅
- §8 CLI scan/build-wiki → Task 11; enrich/summarize deferred. ✅ Wiki output to separate vault → Tasks 1, 11. ✅
- §9 testing (fixtures, interfaces behind seams, ruff+pytest CI) → Tasks 1, 6 (injectable loader), all tests. ✅
- §6 lp → out of scope (M2). ✅

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — every code step is complete. The one inline note (Task 4 Step 4) corrects a test expectation explicitly with the exact value. ✅

**3. Type consistency:** `TrackRecord`/`SourceFile`/`RawTags` field names are consistent across Tasks 2, 5, 6, 7, 10. `Store` method names (`upsert`, `record_drm`, `has_signature`, `iter_artists`, `albums_for_artist`, `tracks_for_album`, `drm_count`) match between Task 5 definition and Tasks 9–11 consumers. `file_signature` returns `(hash, mtime, size)` consistently in Task 10. `MutagenTagReader()` no-arg construction matches the CLI monkeypatch in Task 11. ✅
