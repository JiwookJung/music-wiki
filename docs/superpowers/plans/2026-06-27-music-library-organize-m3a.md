# music-wiki M3-A (rule-based classify + organize) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify every album into one of 7 genre buckets by rules over its (recovered) genre tag + Korean/guitar signals, let the user confirm low-confidence cases via a CSV round-trip, then copy the library into a `genre/artist/album/track` tree on `/home` (originals untouched, dry-run by default).

**Architecture:** A new `organize` package on top of M1's `core`. `buckets` holds the taxonomy + keyword rules; `classify` writes a bucket+confidence per album into SQLite (the SSOT); `review` exports low-confidence albums to CSV and re-imports confirmations; `plan` computes target paths from the DB; `apply` copies files idempotently. The M1 `Store` gains four genre/path columns (non-destructive migration) and a few query/write methods.

**Tech Stack:** Python 3.11, stdlib `sqlite3`/`csv`/`shutil`/`pathlib`, `pytest`, `ruff`. Reuses `core.encoding.recover_text` and `core.wiki.safe_filename`.

## Global Constraints

Copied verbatim from `docs/superpowers/specs/2026-06-27-music-library-organize-design.md`. Every task implicitly includes these.

- Python 3.11.
- The source library at `/mnt/win/memory/음악` is **read-only — copy only, never modify/move/re-tag**. Organized output goes to ext4 `/home`.
- `apply` is **dry-run by default**; copying only happens with an explicit `--apply` / `dry_run=False`.
- Classification granularity is **album-level** (one bucket per album).
- The 7 buckets + fallback, with these **exact folder names**: `클래식`, `가요`, `재즈`, `팝`, `제3세계`, `클래식기타`, `경음악_OST`, and `미분류` (fallback).
- Every path component is sanitized with `core.wiki.safe_filename`.
- Re-runs are **idempotent** (classify/plan/apply all safe to re-run).
- DRM `.enc` files are **excluded from the copy** (they have no track row; `Store.drm_files()` lists them).
- Target root default is `~/music-library/`.
- **M3-A scope: rule-based classification only.** External DB (MusicBrainz/Discogs) and LLM layers are deferred to a separate M3-B plan — do not implement `--enrich-genre`/`--classify-llm` here.

**Reuse (already implemented in M1):** `core.encoding.recover_text(s) -> str|None`; `core.wiki.safe_filename(name) -> str`; `Store.open(path)`, `Store.init_schema()`, `Store.iter_artists()`, `Store.albums_for_artist(artist_id)`, `Store.tracks_for_album(album_id)`, `Store.drm_files() -> list[str]`. `AlbumRow` currently has `(id, title, year, label, genres: list[str], has_digital, has_vinyl, cover_path)`.

## File Structure

```
src/music_wiki/organize/__init__.py            # new package
src/music_wiki/organize/buckets.py             # taxonomy + rule classifier
src/music_wiki/organize/classify.py            # classify_albums(store) -> int
src/music_wiki/organize/review.py              # export_review / import_review
src/music_wiki/organize/plan.py                # build_plan(store, target_root) -> [CopyOp]
src/music_wiki/organize/apply.py               # run_plan(ops, store, dry_run) -> ApplyStats
src/music_wiki/core/store.py                   # MODIFY: migration + genre/organize columns + methods
src/music_wiki/cli.py                          # MODIFY: classify/review-export/review-import/organize
tests/test_buckets.py
tests/test_store_organize.py
tests/test_classify.py
tests/test_review.py
tests/test_plan.py
tests/test_apply.py
tests/test_cli_organize.py
```

---

### Task 1: Store migration + genre/organize columns and methods

**Files:**
- Modify: `src/music_wiki/core/store.py`
- Test: `tests/test_store_organize.py`

**Interfaces:**
- Consumes: existing `Store`, `AlbumRow`, M1 `TrackRecord`/`SourceFile`.
- Produces:
  - Non-destructive migration in `init_schema()`: adds `album.genre_bucket TEXT`, `album.genre_confidence REAL`, `album.genre_source TEXT`, `source_file.organized_path TEXT` if missing.
  - `AlbumRow` extended with `genre_bucket: str|None`, `genre_confidence: float|None`, `genre_source: str|None` (appended after `cover_path`); `albums_for_artist` returns them.
  - `Store.set_album_genre(album_id: int, bucket: str|None, confidence: float|None, source: str) -> None`.
  - `Store.set_organized_path(abs_path: str, organized_path: str) -> None`.
  - `Store.iter_organizable() -> list[OrganizeRow]` where `OrganizeRow(abs_path, fmt, genre_bucket, artist_name, album_title, disc_no, track_no, track_title)` — JOIN of non-DRM `source_file → track → album → artist`.

- [ ] **Step 1: Write the failing tests**

`tests/test_store_organize.py`:
```python
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def _rec(path, hash_, artist="IU", album="Lilac", title="Lilac", track_no=1, genres=None):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title,
        track_no=track_no, disc_no=None, year=2021, label="EDAM",
        genres=genres if genres is not None else ["Ballad"], duration_s=180.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_album_genre_columns_default_none_and_set():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket is None and album.genre_confidence is None
    s.set_album_genre(album.id, "가요", 0.9, "rule")
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "가요"
    assert album.genre_confidence == 0.9
    assert album.genre_source == "rule"


def test_iter_organizable_joins_non_drm_only():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    s.record_drm(SourceFile(abs_path="/x/a.enc", content_hash="d1", mtime=1.0,
                            fmt="enc", is_drm=True))
    rows = s.iter_organizable()
    assert len(rows) == 1
    r = rows[0]
    assert r.abs_path == "/x/1.mp3" and r.artist_name == "IU"
    assert r.album_title == "Lilac" and r.track_title == "Lilac" and r.track_no == 1


def test_iter_organizable_yields_one_row_per_source_file():
    s = _store()
    # two different files resolving to the SAME track (album/disc/track/title)
    s.upsert(_rec("/x/1.mp3", "h1"))
    s.upsert(_rec("/x/2.mp3", "h2"))
    rows = s.iter_organizable()
    assert {r.abs_path for r in rows} == {"/x/1.mp3", "/x/2.mp3"}


def test_set_organized_path():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    s.set_organized_path("/x/1.mp3", "/home/lib/가요/IU/Lilac/01 - Lilac.mp3")
    row = s.conn.execute(
        "SELECT organized_path FROM source_file WHERE abs_path=?", ("/x/1.mp3",)
    ).fetchone()
    assert row[0] == "/home/lib/가요/IU/Lilac/01 - Lilac.mp3"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_store_organize.py -v`
Expected: FAIL (e.g. `AttributeError: 'AlbumRow' object has no attribute 'genre_bucket'` / `Store has no attribute 'set_album_genre'`).

- [ ] **Step 3: Implement migration, extended AlbumRow, OrganizeRow, and methods**

In `src/music_wiki/core/store.py`:

(a) Add `OrganizeRow` next to the other row dataclasses:
```python
@dataclass
class OrganizeRow:
    abs_path: str
    fmt: str
    genre_bucket: str | None
    artist_name: str
    album_title: str
    disc_no: int | None
    track_no: int | None
    track_title: str
```

(b) Extend `AlbumRow` (append three fields after `cover_path`):
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
```

(c) In `init_schema`, call a migration after the script:
```python
    def init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        album_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(album)")}
        for col, decl in (("genre_bucket", "TEXT"), ("genre_confidence", "REAL"),
                          ("genre_source", "TEXT")):
            if col not in album_cols:
                self.conn.execute(f"ALTER TABLE album ADD COLUMN {col} {decl}")
        sf_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(source_file)")}
        if "organized_path" not in sf_cols:
            self.conn.execute("ALTER TABLE source_file ADD COLUMN organized_path TEXT")
```

(d) Update `albums_for_artist` to select and construct the new fields:
```python
    def albums_for_artist(self, artist_id: int) -> list[AlbumRow]:
        cur = self.conn.execute(
            "SELECT id, title, year, label, genres, has_digital, has_vinyl, cover_path,"
            " genre_bucket, genre_confidence, genre_source"
            " FROM album WHERE artist_id=? ORDER BY year, title", (artist_id,)
        )
        return [
            AlbumRow(r[0], r[1], r[2], r[3], json.loads(r[4]), bool(r[5]), bool(r[6]),
                     r[7], r[8], r[9], r[10])
            for r in cur.fetchall()
        ]
```

(e) Add the new write/read methods to the `Store` class:
```python
    def set_album_genre(self, album_id: int, bucket: str | None,
                        confidence: float | None, source: str) -> None:
        self.conn.execute(
            "UPDATE album SET genre_bucket=?, genre_confidence=?, genre_source=?"
            " WHERE id=?", (bucket, confidence, source, album_id)
        )
        self.conn.commit()

    def set_organized_path(self, abs_path: str, organized_path: str) -> None:
        self.conn.execute(
            "UPDATE source_file SET organized_path=? WHERE abs_path=?",
            (organized_path, abs_path)
        )
        self.conn.commit()

    def iter_organizable(self) -> list[OrganizeRow]:
        cur = self.conn.execute(
            "SELECT sf.abs_path, sf.fmt, al.genre_bucket, ar.name, al.title,"
            " t.disc_no, t.track_no, t.title"
            " FROM source_file sf"
            " JOIN track t ON sf.track_id = t.id"
            " JOIN album al ON t.album_id = al.id"
            " JOIN artist ar ON al.artist_id = ar.id"
            " WHERE sf.is_drm = 0 AND sf.track_id IS NOT NULL"
            " ORDER BY ar.name, al.title, t.disc_no, t.track_no"
        )
        return [OrganizeRow(*r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run to verify it passes (and M1 store tests still green)**

Run: `pytest tests/test_store_organize.py tests/test_store.py -v`
Expected: PASS (new file + existing M1 store tests unaffected — the added `AlbumRow` fields and columns don't change M1 assertions).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/store.py tests/test_store_organize.py
git commit -m "feat: store migration for genre/organized_path columns + organize queries"
```

---

### Task 2: Bucket taxonomy + rule classifier

**Files:**
- Create: `src/music_wiki/organize/__init__.py` (empty), `src/music_wiki/organize/buckets.py`
- Test: `tests/test_buckets.py`

**Interfaces:**
- Consumes: `core.encoding.recover_text`.
- Produces:
  - `BUCKETS: list[str]` (the 7) and `UNCLASSIFIED = "미분류"`.
  - `RuleResult(bucket: str, confidence: float, signals: str)`.
  - `classify_by_rules(genres: list[str], artist: str, titles: list[str]) -> RuleResult`.

- [ ] **Step 1: Write the failing tests**

`tests/test_buckets.py`:
```python
from music_wiki.organize.buckets import classify_by_rules, BUCKETS, UNCLASSIFIED


def c(genres, artist="x", titles=("y",)):
    return classify_by_rules(list(genres), artist, list(titles))


def test_clean_single_genre_high_confidence():
    assert c(["Classical"]).bucket == "클래식"
    assert c(["Classical"]).confidence == 0.9
    assert c(["Jazz"]).bucket == "재즈"
    assert c(["Tango"]).bucket == "제3세계"
    assert c(["Soundtrack"]).bucket == "경음악_OST"


def test_classical_guitar_overrides_classical():
    r = c(["Classical Guitar"], artist="Segovia", titles=["Asturias"])
    assert r.bucket == "클래식기타" and r.confidence == 0.9


def test_korean_gating_for_가요():
    # Korean text + ballad keyword → 가요
    assert c(["Ballad"], artist="김광석", titles=["이등병의 편지"]).bucket == "가요"
    # English ballad, no Korean → not 가요 (no other rule) → 미분류
    assert c(["Ballad"], artist="Michael Bolton", titles=["Song"]).bucket == UNCLASSIFIED


def test_blank_genre_korean_low_confidence_가요():
    r = c(["Other"], artist="아이유", titles=["좋은 날"])
    assert r.bucket == "가요" and r.confidence == 0.4


def test_junk_genre_nonkorean_is_unclassified():
    r = c(["#NIPPONSEI @ IRC.RIZON.NET"], artist="x", titles=["y"])
    assert r.bucket == UNCLASSIFIED and r.confidence == 0.0


def test_multi_match_is_low_confidence():
    r = c(["Jazz(Tango,World Fusion)"], artist="x", titles=["y"])
    assert r.confidence == 0.5
    assert r.bucket in ("재즈", "제3세계")


def test_buckets_constant():
    assert set(BUCKETS) == {"클래식", "가요", "재즈", "팝", "제3세계", "클래식기타", "경음악_OST"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_buckets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.organize'`.

- [ ] **Step 3: Implement the taxonomy + classifier**

Create `src/music_wiki/organize/__init__.py` (empty).

`src/music_wiki/organize/buckets.py`:
```python
from __future__ import annotations

import re
from dataclasses import dataclass

from music_wiki.core.encoding import recover_text

BUCKETS = ["클래식", "가요", "재즈", "팝", "제3세계", "클래식기타", "경음악_OST"]
UNCLASSIFIED = "미분류"

_HANGUL = re.compile(r"[가-힣]")

# bucket -> keyword substrings matched against the recovered, lowercased genre tag
_RULES: list[tuple[str, list[str]]] = [
    ("재즈", ["jazz", "swing", "bebop", "재즈"]),
    ("제3세계", ["world", "월드", "tango", "탱고", "latin", "bossa", "samba", "mpb",
              "folklore", "flamenco", "fado", "brazil", "brasil", "ethnic",
              "national folk", "제3세계"]),
    ("경음악_OST", ["ost", "o.s.t", "soundtrack", "screen music", "score", "경음악",
                 "easy listening", "instrumental", "연주", "newage", "new age"]),
    ("클래식", ["classical", "클래식", "opera", "오페라", "chamber", "symphony", "교향",
             "협주", "baroque", "romantic", "sonata", "clássica", "choral", "concerto"]),
    ("팝", ["pop", "rock", "r&b", "soul", "funk", "electronic", "dance", "hip hop",
          "hiphop", "jpop", "j-pop", "techno"]),
    ("가요", ["가요", "발라드", "ballad", "트로트", "trot", "kpop", "k-pop", "댄스"]),
]

# when multiple buckets match, the earliest here wins (and confidence drops)
_PRIORITY = ["클래식기타", "클래식", "재즈", "제3세계", "가요", "경음악_OST", "팝"]


@dataclass
class RuleResult:
    bucket: str
    confidence: float
    signals: str


def classify_by_rules(genres: list[str], artist: str, titles: list[str]) -> RuleResult:
    raw = " ".join((recover_text(g) or "") for g in genres).lower().strip()
    hay = " ".join([raw, (artist or "").lower(), " ".join(titles).lower()])
    is_korean = bool(_HANGUL.search(artist or "")) or any(_HANGUL.search(t or "") for t in titles)
    has_guitar = any(k in hay for k in ("classical guitar", "클래식기타", "guitar", "기타"))

    matched: list[str] = []
    signals: list[str] = []
    for bucket, kws in _RULES:
        hit = next((kw for kw in kws if kw in raw), None)
        if hit is None:
            continue
        if bucket == "가요" and not is_korean:
            continue  # English "ballad/pop" without Korean is not 가요
        matched.append(bucket)
        signals.append(f"{bucket}:{hit}")

    if "클래식" in matched and has_guitar:
        matched = ["클래식기타" if b == "클래식" else b for b in matched]
        signals.append("guitar")
    matched = list(dict.fromkeys(matched))

    if len(matched) == 1:
        return RuleResult(matched[0], 0.9, ";".join(signals))
    if len(matched) > 1:
        chosen = next((b for b in _PRIORITY if b in matched), matched[0])
        return RuleResult(chosen, 0.5, ";".join(signals) + f";multi->{chosen}")
    if is_korean:
        return RuleResult("가요", 0.4, "no-tag;korean->가요")
    return RuleResult(UNCLASSIFIED, 0.0, f"no-tag;raw={raw!r}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_buckets.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/__init__.py src/music_wiki/organize/buckets.py tests/test_buckets.py
git commit -m "feat: 7-bucket genre taxonomy + rule classifier"
```

---

### Task 3: Classify albums into the DB

**Files:**
- Create: `src/music_wiki/organize/classify.py`
- Test: `tests/test_classify.py`

**Interfaces:**
- Consumes: `Store` (`iter_artists`, `albums_for_artist`, `tracks_for_album`, `set_album_genre`); `classify_by_rules` (Task 2).
- Produces: `classify_albums(store: Store) -> int` — classifies every album by rules, writing `genre_bucket/confidence` with `source="rule"`; **skips albums whose `genre_source == "manual"`** (don't clobber human decisions). Returns the count classified.

- [ ] **Step 1: Write the failing tests**

`tests/test_classify.py`:
```python
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.classify import classify_albums


def _rec(path, hash_, artist, album, title, genres):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=1,
        disc_no=None, year=2000, label=None, genres=genres, duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_classify_writes_buckets():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "Bill Evans", "Waltz for Debby", "My Foolish Heart", ["Jazz"]))
    s.upsert(_rec("/b.mp3", "h2", "김광석", "다시부르기", "이등병의 편지", ["Ballad"]))
    n = classify_albums(s)
    assert n == 2
    by_artist = {a.name: s.albums_for_artist(a.id)[0] for a in s.iter_artists()}
    assert by_artist["Bill Evans"].genre_bucket == "재즈"
    assert by_artist["김광석"].genre_bucket == "가요"
    assert by_artist["Bill Evans"].genre_source == "rule"


def test_classify_skips_manual():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "Bill Evans", "Waltz", "x", ["Jazz"]))
    album_id = s.albums_for_artist(s.iter_artists()[0].id)[0].id
    s.set_album_genre(album_id, "팝", 1.0, "manual")
    classify_albums(s)
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "팝" and album.genre_source == "manual"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_classify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.organize.classify'`.

- [ ] **Step 3: Implement classify_albums**

`src/music_wiki/organize/classify.py`:
```python
from __future__ import annotations

from music_wiki.core.store import Store

from .buckets import classify_by_rules


def classify_albums(store: Store) -> int:
    """Classify every album by rules, writing genre_bucket/confidence (source='rule').
    Albums already set by a human (genre_source == 'manual') are left untouched.
    Idempotent: re-running re-derives the same rule results."""
    n = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_source == "manual":
                continue
            titles = [t.title for t in store.tracks_for_album(album.id)]
            res = classify_by_rules(album.genres, artist.name, titles)
            store.set_album_genre(album.id, res.bucket, res.confidence, "rule")
            n += 1
    return n
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_classify.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/classify.py tests/test_classify.py
git commit -m "feat: rule-based album classification into the DB"
```

---

### Task 4: Review CSV round-trip

**Files:**
- Create: `src/music_wiki/organize/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `Store`; `classify_by_rules`, `BUCKETS`, `UNCLASSIFIED` (Task 2).
- Produces:
  - `export_review(store: Store, out_path: str, threshold: float = 0.8) -> int` — writes albums with `confidence < threshold` OR `bucket in (None, 미분류)` (and `source != "manual"`) to a CSV with columns `album_id, artist, album, proposed_bucket, confidence, source, signals`. Returns row count.
  - `import_review(store: Store, in_path: str) -> int` — reads the CSV; for each row whose `proposed_bucket` is a valid bucket (or 미분류), calls `set_album_genre(album_id, bucket, 1.0, "manual")`. Skips invalid/blank buckets. Returns applied count.

- [ ] **Step 1: Write the failing tests**

`tests/test_review.py`:
```python
from pathlib import Path

from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.review import export_review, import_review


def _rec(path, hash_, artist, album, title, genres):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=1,
        disc_no=None, year=2000, label=None, genres=genres, duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _seeded():
    s = Store.open(":memory:")
    s.init_schema()
    s.upsert(_rec("/a.mp3", "h1", "Bill Evans", "Waltz", "x", ["Jazz"]))       # high conf
    s.upsert(_rec("/b.mp3", "h2", "VA", "Comp", "y", ["#IRC JUNK"]))           # 미분류
    classify_albums(s)
    return s


def test_export_only_low_confidence(tmp_path: Path):
    s = _seeded()
    out = tmp_path / "review.csv"
    n = export_review(s, str(out), threshold=0.8)
    text = out.read_text(encoding="utf-8")
    assert n == 1                       # only the 미분류 album
    assert "Comp" in text and "Waltz" not in text
    assert "signals" in text            # header present


def test_import_applies_manual_buckets(tmp_path: Path):
    s = _seeded()
    out = tmp_path / "review.csv"
    export_review(s, str(out), threshold=0.8)
    # user edits the proposed_bucket to a real bucket
    rows = out.read_text(encoding="utf-8").replace("미분류", "제3세계")
    out.write_text(rows, encoding="utf-8")
    applied = import_review(s, str(out))
    assert applied == 1
    comp = next(a for ar in s.iter_artists() for a in s.albums_for_artist(ar.id)
                if a.title == "Comp")
    assert comp.genre_bucket == "제3세계" and comp.genre_source == "manual"


def test_import_skips_invalid_bucket(tmp_path: Path):
    s = _seeded()
    out = tmp_path / "review.csv"
    export_review(s, str(out), threshold=0.8)
    out.write_text(out.read_text(encoding="utf-8").replace("미분류", "NOTABUCKET"),
                   encoding="utf-8")
    assert import_review(s, str(out)) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_review.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.organize.review'`.

- [ ] **Step 3: Implement review**

`src/music_wiki/organize/review.py`:
```python
from __future__ import annotations

import csv

from music_wiki.core.store import Store

from .buckets import BUCKETS, UNCLASSIFIED, classify_by_rules

_FIELDS = ["album_id", "artist", "album", "proposed_bucket", "confidence", "source", "signals"]


def export_review(store: Store, out_path: str, threshold: float = 0.8) -> int:
    rows = []
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_source == "manual":
                continue
            conf = album.genre_confidence if album.genre_confidence is not None else 0.0
            if conf >= threshold and album.genre_bucket not in (None, UNCLASSIFIED):
                continue
            titles = [t.title for t in store.tracks_for_album(album.id)]
            res = classify_by_rules(album.genres, artist.name, titles)
            rows.append({
                "album_id": album.id, "artist": artist.name, "album": album.title,
                "proposed_bucket": album.genre_bucket or UNCLASSIFIED,
                "confidence": f"{conf:.2f}", "source": album.genre_source or "",
                "signals": res.signals,
            })
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def import_review(store: Store, in_path: str) -> int:
    n = 0
    with open(in_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bucket = (row.get("proposed_bucket") or "").strip()
            if bucket not in BUCKETS and bucket != UNCLASSIFIED:
                continue
            store.set_album_genre(int(row["album_id"]), bucket, 1.0, "manual")
            n += 1
    return n
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_review.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/review.py tests/test_review.py
git commit -m "feat: confidence-gated genre review CSV round-trip"
```

---

### Task 5: Build the copy plan

**Files:**
- Create: `src/music_wiki/organize/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `Store.iter_organizable()` (Task 1); `core.wiki.safe_filename`; `UNCLASSIFIED` (Task 2).
- Produces:
  - `CopyOp(src: str, dst: str)`.
  - `build_plan(store: Store, target_root: str) -> list[CopyOp]` — target path `{root}/{safe(bucket)}/{safe(artist)}/{safe(album)}/{NN - safe(title)}.{ext}`. `NN` = `disc-track` (zero-padded track) when disc is set, else zero-padded `track`; when `track_no` is None, just `safe(title)`. Bucket falls back to `미분류`. Duplicate target paths (same track via multiple source files) collapse to **one** op (first wins).

- [ ] **Step 1: Write the failing tests**

`tests/test_plan.py`:
```python
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.plan import build_plan


def _rec(path, hash_, artist, album, title, track_no, genres, disc_no=None):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=track_no,
        disc_no=disc_no, year=2000, label=None, genres=genres, duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_plan_path_layout():
    s = _store()
    s.upsert(_rec("/src/a.mp3", "h1", "Bill Evans", "Waltz for Debby",
                  "My Foolish Heart", 1, ["Jazz"]))
    classify_albums(s)
    ops = build_plan(s, "/home/lib")
    assert len(ops) == 1
    assert ops[0].src == "/src/a.mp3"
    assert ops[0].dst == "/home/lib/재즈/Bill Evans/Waltz for Debby/01 - My Foolish Heart.mp3"


def test_plan_disc_prefix_and_unclassified():
    s = _store()
    s.upsert(_rec("/src/b.mp3", "h2", "VA", "Comp", "Track", 3, ["#JUNK"], disc_no=2))
    classify_albums(s)  # junk → 미분류
    dst = build_plan(s, "/home/lib")[0].dst
    assert dst == "/home/lib/미분류/VA/Comp/2-03 - Track.mp3"


def test_plan_sanitizes_special_chars():
    s = _store()
    s.upsert(_rec("/src/c.mp3", "h3", "AC/DC", "Live: At X", "T:1", 1, ["Rock"]))
    classify_albums(s)
    dst = build_plan(s, "/home/lib")[0].dst
    assert dst == "/home/lib/팝/AC_DC/Live_ At X/01 - T_1.mp3"


def test_plan_dedups_same_track_multiple_sources():
    s = _store()
    s.upsert(_rec("/src/1.mp3", "h1", "IU", "Lilac", "Lilac", 1, ["Ballad"]))
    s.upsert(_rec("/src/2.mp3", "h2", "IU", "Lilac", "Lilac", 1, ["Ballad"]))
    classify_albums(s)
    ops = build_plan(s, "/home/lib")
    assert len(ops) == 1  # one target path → one copy
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_plan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.organize.plan'`.

- [ ] **Step 3: Implement build_plan**

`src/music_wiki/organize/plan.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from music_wiki.core.store import Store
from music_wiki.core.wiki import safe_filename

from .buckets import UNCLASSIFIED


@dataclass
class CopyOp:
    src: str
    dst: str


def _track_filename(disc_no: int | None, track_no: int | None, title: str, ext: str) -> str:
    safe_title = safe_filename(title)
    if track_no is None:
        return f"{safe_title}.{ext}"
    num = f"{disc_no}-{track_no:02d}" if disc_no is not None else f"{track_no:02d}"
    return f"{num} - {safe_title}.{ext}"


def build_plan(store: Store, target_root: str) -> list[CopyOp]:
    ops: list[CopyOp] = []
    seen: set[str] = set()
    root = target_root.rstrip("/")
    for r in store.iter_organizable():
        bucket = r.genre_bucket or UNCLASSIFIED
        ext = (r.fmt or "").lower() or PurePosixPath(r.abs_path).suffix.lstrip(".").lower()
        fname = _track_filename(r.disc_no, r.track_no, r.track_title, ext)
        dst = "/".join([root, safe_filename(bucket), safe_filename(r.artist_name),
                        safe_filename(r.album_title), fname])
        if dst in seen:
            continue  # same track reached via multiple source files → copy once
        seen.add(dst)
        ops.append(CopyOp(src=r.abs_path, dst=dst))
    return ops
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_plan.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/plan.py tests/test_plan.py
git commit -m "feat: build genre/artist/album/track copy plan from the DB"
```

---

### Task 6: Apply the plan (copy, dry-run default, idempotent)

**Files:**
- Create: `src/music_wiki/organize/apply.py`
- Test: `tests/test_apply.py`

**Interfaces:**
- Consumes: `CopyOp` (Task 5); optional `Store` for `set_organized_path`.
- Produces:
  - `ApplyStats(planned: int, copied: int, skipped: int, errors: int)`.
  - `run_plan(ops: list[CopyOp], store: Store | None = None, *, dry_run: bool = True) -> ApplyStats` — for each op: if `dst` exists with the same size as `src`, count `skipped` (and record `organized_path` if `store`); else if `dry_run`, do nothing more; else `mkdir -p` parent + `shutil.copy2` and count `copied` (and record). A per-op exception counts `errors` and continues. `planned == len(ops)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_apply.py`:
```python
from pathlib import Path

from music_wiki.organize.apply import run_plan
from music_wiki.organize.plan import CopyOp


def test_dry_run_copies_nothing(tmp_path: Path):
    src = tmp_path / "s.mp3"
    src.write_bytes(b"audio")
    dst = tmp_path / "out" / "재즈" / "A" / "Alb" / "01 - T.mp3"
    stats = run_plan([CopyOp(str(src), str(dst))], dry_run=True)
    assert stats.planned == 1 and stats.copied == 0 and stats.skipped == 0
    assert not dst.exists()


def test_apply_copies_and_is_idempotent(tmp_path: Path):
    src = tmp_path / "s.mp3"
    src.write_bytes(b"audio")
    dst = tmp_path / "out" / "재즈" / "A" / "Alb" / "01 - T.mp3"
    ops = [CopyOp(str(src), str(dst))]
    s1 = run_plan(ops, dry_run=False)
    assert s1.copied == 1 and dst.read_bytes() == b"audio"
    s2 = run_plan(ops, dry_run=False)   # re-run
    assert s2.copied == 0 and s2.skipped == 1


def test_apply_counts_errors_and_continues(tmp_path: Path):
    good_src = tmp_path / "g.mp3"
    good_src.write_bytes(b"x")
    ops = [
        CopyOp(str(tmp_path / "missing.mp3"), str(tmp_path / "out" / "a.mp3")),  # src absent → error
        CopyOp(str(good_src), str(tmp_path / "out" / "b.mp3")),
    ]
    stats = run_plan(ops, dry_run=False)
    assert stats.errors == 1 and stats.copied == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_apply.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.organize.apply'`.

- [ ] **Step 3: Implement run_plan**

`src/music_wiki/organize/apply.py`:
```python
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from music_wiki.core.store import Store

from .plan import CopyOp


@dataclass
class ApplyStats:
    planned: int = 0
    copied: int = 0
    skipped: int = 0
    errors: int = 0


def run_plan(ops: list[CopyOp], store: Store | None = None, *,
             dry_run: bool = True) -> ApplyStats:
    stats = ApplyStats(planned=len(ops))
    for op in ops:
        try:
            dst = Path(op.dst)
            if dst.exists() and dst.stat().st_size == os.path.getsize(op.src):
                stats.skipped += 1
                if store is not None:
                    store.set_organized_path(op.src, op.dst)
                continue
            if dry_run:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(op.src, dst)
            stats.copied += 1
            if store is not None:
                store.set_organized_path(op.src, op.dst)
        except Exception:
            stats.errors += 1
    return stats
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_apply.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/apply.py tests/test_apply.py
git commit -m "feat: apply copy plan (dry-run default, idempotent, error-isolated)"
```

---

### Task 7: CLI subcommands

**Files:**
- Modify: `src/music_wiki/cli.py`
- Test: `tests/test_cli_organize.py`

**Interfaces:**
- Consumes: `_store_at` (existing M1 CLI helper), `Config`; `classify_albums`, `export_review`, `import_review`, `build_plan`, `run_plan`.
- Produces four subcommands on the existing `music-wiki` parser:
  - `classify [--db PATH]`
  - `review-export [--db PATH] [--out review.csv] [--threshold 0.8]`
  - `review-import [--db PATH] [--in review.csv]`
  - `organize [--db PATH] [--target ~/music-library] [--apply]` (dry-run unless `--apply`).

- [ ] **Step 1: Write the failing test (end-to-end on a temp DB)**

`tests/test_cli_organize.py`:
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
        source=SourceFile(abs_path=str(src_file), content_hash="h1", mtime=1.0, fmt="mp3"),
    ))


def test_classify_then_organize_dry_run_then_apply(tmp_path: Path):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"audio")
    db = tmp_path / "wiki.db"
    target = tmp_path / "lib"
    _seed_db(db, src)

    assert main(["classify", "--db", str(db)]) == 0
    # dry-run: nothing copied
    assert main(["organize", "--db", str(db), "--target", str(target)]) == 0
    assert not (target / "재즈").exists()
    # apply: file lands in the genre tree
    assert main(["organize", "--db", str(db), "--target", str(target), "--apply"]) == 0
    assert (target / "재즈" / "Bill Evans" / "Waltz" / "01 - T.mp3").read_bytes() == b"audio"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_cli_organize.py -v`
Expected: FAIL (`argument cmd: invalid choice: 'classify'`).

- [ ] **Step 3: Wire the subcommands into the CLI**

In `src/music_wiki/cli.py`, add imports near the existing ones:
```python
from music_wiki.organize.apply import run_plan
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.plan import build_plan
from music_wiki.organize.review import export_review, import_review
```

Add the command handlers (next to `_cmd_scan` / `_cmd_build_wiki`):
```python
def _cmd_classify(args) -> int:
    store = _store_at(args.db)
    n = classify_albums(store)
    print(f"classified {n} albums (rules)")
    return 0


def _cmd_review_export(args) -> int:
    store = _store_at(args.db)
    n = export_review(store, args.out, threshold=args.threshold)
    print(f"exported {n} albums to {args.out} (confidence < {args.threshold} or 미분류)")
    return 0


def _cmd_review_import(args) -> int:
    store = _store_at(args.db)
    n = import_review(store, args.in_path)
    print(f"applied {n} manual classifications")
    return 0


def _cmd_organize(args) -> int:
    store = _store_at(args.db)
    ops = build_plan(store, args.target)
    stats = run_plan(ops, store, dry_run=not args.apply)
    if args.apply:
        print(f"[APPLIED] planned={stats.planned} copied={stats.copied} "
              f"skipped={stats.skipped} errors={stats.errors}")
    else:
        would = stats.planned - stats.skipped - stats.errors
        print(f"[DRY-RUN] planned={stats.planned} would_copy={would} "
              f"already={stats.skipped} target={args.target}  (use --apply to copy)")
    return 0
```

Register them inside `main`, after the existing `build-wiki` subparser and before `parser.parse_args`:
```python
    import os

    p_classify = sub.add_parser("classify", help="앨범 장르 버킷 산출(규칙)")
    p_classify.add_argument("--db", default=str(cfg.db_path))
    p_classify.set_defaults(func=_cmd_classify)

    p_rexport = sub.add_parser("review-export", help="저신뢰·미분류 앨범 CSV 출력")
    p_rexport.add_argument("--db", default=str(cfg.db_path))
    p_rexport.add_argument("--out", default="review.csv")
    p_rexport.add_argument("--threshold", type=float, default=0.8)
    p_rexport.set_defaults(func=_cmd_review_export)

    p_rimport = sub.add_parser("review-import", help="수정된 장르 확정")
    p_rimport.add_argument("--db", default=str(cfg.db_path))
    p_rimport.add_argument("--in", dest="in_path", default="review.csv")
    p_rimport.set_defaults(func=_cmd_review_import)

    p_org = sub.add_parser("organize", help="장르 트리로 복사(기본 dry-run)")
    p_org.add_argument("--db", default=str(cfg.db_path))
    p_org.add_argument("--target", default=os.path.expanduser("~/music-library"))
    p_org.add_argument("--apply", action="store_true")
    p_org.set_defaults(func=_cmd_organize)
```

(Place the `import os` at the top of the file with the other imports rather than inside `main` if the file doesn't already import it.)

- [ ] **Step 4: Run to verify it passes, then the full suite + lint**

Run: `pytest tests/test_cli_organize.py -v`
Expected: PASS.

Run: `pytest -q && ruff check .`
Expected: all tests PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/cli.py tests/test_cli_organize.py
git commit -m "feat: CLI classify / review-export / review-import / organize"
```

---

### Task 8: Manual verification against the real library (controller-run)

**Files:** none (manual smoke test; read-only on source).

- [ ] **Step 1: Classify a real subtree and inspect buckets**

Reuse the M1 smoke DB or scan a small folder first, then:
```bash
music-wiki scan --source "/mnt/win/memory/음악/musicmusic/클래식" --db /tmp/mw-org.db
music-wiki classify --db /tmp/mw-org.db
music-wiki review-export --db /tmp/mw-org.db --out /tmp/review.csv --threshold 0.8
```
Expected: `classified N albums`; open `/tmp/review.csv` and confirm clean classical/jazz albums are NOT listed (high confidence) while junk/ambiguous ones are, with readable `signals`.

- [ ] **Step 2: Dry-run organize and eyeball the tree**

```bash
music-wiki organize --db /tmp/mw-org.db --target /tmp/mw-lib
```
Expected: `[DRY-RUN] planned=… would_copy=… target=/tmp/mw-lib  (use --apply to copy)`; nothing written yet.

- [ ] **Step 3: Apply on the small subtree and confirm layout + idempotency**

```bash
music-wiki organize --db /tmp/mw-org.db --target /tmp/mw-lib --apply
ls /tmp/mw-lib            # expect 클래식/ (and maybe 미분류/) genre dirs
music-wiki organize --db /tmp/mw-org.db --target /tmp/mw-lib --apply   # re-run
```
Expected: first run copies; tree is `클래식/<artist>/<album>/NN - title.ext`; re-run shows `copied=0 skipped=…` (idempotent). Confirm Korean names render with no mojibake.

- [ ] **Step 4: Record findings**

Note any albums misbucketed by rules (feed the M3-B external/LLM backlog and the review CSV). No commit (scratch DB/library under `/tmp`).

---

## Self-Review

**1. Spec coverage:**
- §4 buckets + folder names → Task 2 (`BUCKETS`, exact folder strings used in Task 5 paths). ✅
- §5 classify L1 rules (tag recover, Korean/guitar, confidence) → Tasks 2–3. L2/L3 external+LLM → out of scope (M3-B), per Global Constraints. ✅
- §6 review (confidence-gated CSV export/import, manual source) → Task 4. ✅
- §7 plan (path layout, disc prefix, DRM exclusion via `iter_organizable` WHERE is_drm=0, 미분류 fallback, dedup) → Tasks 1, 5. ✅
- §8 apply (dry-run default, idempotent, error isolation, organized_path) → Task 6. ✅
- §9 DB columns (non-destructive migration) → Task 1. ✅
- §10 CLI (classify/review-export/review-import/organize) → Task 7. ✅
- §12 read-only source/copy, idempotent → Tasks 5/6 (no source writes; size-gated skip). ✅
- §13 testing (rule case table, Korean/guitar, plan paths/DRM/미분류, apply idempotency via tmp fixtures) → all tasks. ✅

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — every code step is complete. ✅

**3. Type consistency:** `OrganizeRow` fields (Task 1) match `build_plan`'s usage (Task 5: `r.genre_bucket/abs_path/fmt/artist_name/album_title/disc_no/track_no/track_title`). `AlbumRow` extension order (Task 1) matches the `albums_for_artist` SELECT/constructor. `RuleResult(bucket, confidence, signals)` (Task 2) matches classify/review usage (Tasks 3–4). `CopyOp(src, dst)` (Task 5) matches `run_plan` (Task 6) and the CLI (Task 7). `set_album_genre(album_id, bucket, confidence, source)` and `set_organized_path(abs_path, organized_path)` signatures are consistent across Tasks 1/3/4/6. CLI `--in` → `dest="in_path"` matches `_cmd_review_import` reading `args.in_path`. ✅
