# music-wiki M3-B1 (MusicBrainz enrichment + L1 refinements) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve genre classification for the albums L1 rules leave low-confidence — by (a) tightening the rule layer (album-title "OST" signal, `hip-hop`/`rap` keywords, Korean-popular→가요 routing) and (b) querying MusicBrainz (free, no key) for low-confidence albums and re-running the rule mapper on the returned genres.

**Architecture:** Two additive pieces on M3-A. The rule classifier (`buckets.classify_by_rules`) gains an optional `album` argument and three small rules; its callers pass the album title. A new `external` package holds a `MusicBrainzClient` interface + an HTTP implementation (injectable fetch/sleep, disk cache, ~1 req/s); `organize.enrich` walks low-confidence albums, looks up genres, and reuses `classify_by_rules` to bucket them with `source="musicbrainz"`. A `classify --enrich-genre` flag runs the enrichment after L1.

**Tech Stack:** Python 3.11, `requests` (HTTP), stdlib `json`/`urllib.parse`/`hashlib`/`time`, `pytest`, `ruff`. Reuses M3-A `core.Store`, `organize.buckets`.

## Global Constraints

- Python 3.11.
- **M3-B1 scope: MusicBrainz L2 + L1 refinements ONLY.** LLM (L3) and Discogs are deferred to a separate M3-B2 plan — do not add `--classify-llm`/Discogs here.
- External clients sit behind an interface; **unit tests inject fakes and make NO live network calls.** Live MusicBrainz calls happen only in the manual-verification task.
- MusicBrainz requires a descriptive `User-Agent` header and ~1 request/second rate limiting; responses are disk-cached (keyed by artist|album).
- Enrichment only touches albums that are **non-manual** and **low-confidence** (`confidence < threshold` or bucket in `{None, 미분류}`); it never overwrites a `manual` decision and only updates when the looked-up result is more confident.
- The taxonomy is unchanged: the 7 buckets + `미분류` ("미분류"). No new buckets.
- The source library is read-only — enrichment reads the DB and the MusicBrainz API, and writes only to the DB.

**Reuse (M3-A, already implemented):** `buckets.classify_by_rules(genres, artist, titles) -> RuleResult(bucket, confidence, signals)`, `buckets._kw_matches(kw, raw)`, `BUCKETS`, `UNCLASSIFIED="미분류"`, `_HANGUL`, `_RULES`, `_PRIORITY`. `Store.iter_artists()`, `Store.albums_for_artist(id)` (AlbumRow has `.title/.genres/.genre_bucket/.genre_confidence/.genre_source`), `Store.tracks_for_album(id)`, `Store.set_album_genre(id, bucket, conf, source)`. `Config.default()`. `cli._store_at(db)`.

## File Structure

```
src/music_wiki/organize/buckets.py        # MODIFY: album param + OST-title + hip-hop/rap + Korean-pop routing
src/music_wiki/organize/classify.py       # MODIFY: pass album.title
src/music_wiki/organize/review.py         # MODIFY: pass album.title (signals reflect new rules)
src/music_wiki/external/__init__.py       # new package
src/music_wiki/external/musicbrainz.py    # MusicBrainzClient protocol + HttpMusicBrainzClient
src/music_wiki/organize/enrich.py         # enrich_genres(store, mb_client, threshold)
src/music_wiki/core/config.py             # MODIFY: musicbrainz_user_agent + mb_cache_dir
src/music_wiki/cli.py                      # MODIFY: classify --enrich-genre
tests/test_buckets.py                      # MODIFY: OST-title / hip-hop-rap / korean-pop tests
tests/test_musicbrainz.py
tests/test_enrich.py
tests/test_cli_enrich.py
```

---

### Task 1: L1 rule refinements

**Files:**
- Modify: `src/music_wiki/organize/buckets.py`, `src/music_wiki/organize/classify.py`, `src/music_wiki/organize/review.py`
- Test: `tests/test_buckets.py`

**Interfaces:**
- Consumes: existing `classify_by_rules` internals.
- Produces: `classify_by_rules(genres: list[str], artist: str, titles: list[str], album: str = "") -> RuleResult`. New behavior:
  - An album title containing an OST signal (`\bost\b`, `o.s.t`, or `soundtrack`, case-insensitive) contributes the `경음악_OST` bucket.
  - `hip-hop` and `rap` are 팝 keywords.
  - When Korean is detected and the **only** matched bucket is `팝`, it is re-routed to `가요` (Korean popular music). `classify.py` and `review.py` pass `album=album.title`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_buckets.py`; update the `c` helper to accept `album`)

First update the existing `c` helper at the top of the test file from:
```python
def c(genres, artist="x", titles=("y",)):
    return classify_by_rules(list(genres), artist, list(titles))
```
to:
```python
def c(genres, artist="x", titles=("y",), album=""):
    return classify_by_rules(list(genres), artist, list(titles), album=album)
```

Then append:
```python
def test_album_title_ost_signal():
    # blank/unmatched genre tag + "OST" in the album title → 경음악_OST
    r = c(["Other"], artist="히사이시 조", titles=["테마"], album="벼랑위의 포뇨 OST")
    assert r.bucket == "경음악_OST"
    # "Ghost" must NOT trigger the \bost\b rule
    assert c([], album="Ghost Stories").bucket != "경음악_OST"
    # "soundtrack" anywhere in the title
    assert c([], album="Original Soundtrack").bucket == "경음악_OST"


def test_hiphop_and_rap_map_to_pop():
    assert c(["rap / hip-hop"]).bucket == "팝"   # was 미분류 before (hyphen miss)
    assert c(["Hip-Hop"]).bucket == "팝"


def test_korean_popular_routes_to_가요():
    # Korean artist + a generic 팝 tag → 가요 (not western 팝)
    assert c(["Pop"], artist="아이유", titles=["좋은 날"]).bucket == "가요"
    assert c(["Hip-Hop"], artist="비와이", titles=["forever"]).bucket == "가요"
    # non-Korean pop stays 팝
    assert c(["Pop"], artist="Dua Lipa", titles=["Levitating"]).bucket == "팝"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_buckets.py -v`
Expected: the new tests FAIL (e.g. `c()` got unexpected keyword `album`, then bucket mismatches).

- [ ] **Step 3: Implement the rule changes**

In `src/music_wiki/organize/buckets.py`:

(a) Add `hip-hop` and `rap` to the 팝 keyword list inside `_RULES` (the `("팝", [...])` entry) — append `"hip-hop", "rap"`:
```python
    ("팝", ["pop", "rock", "r&b", "soul", "funk", "electronic", "dance", "hip hop",
          "hiphop", "hip-hop", "rap", "jpop", "j-pop", "techno"]),
```

(b) Add an OST-signal helper (module level, near `_HANGUL`):
```python
def _has_ost_signal(album: str) -> bool:
    a = (album or "").lower()
    return bool(re.search(r"\bost\b", a)) or "o.s.t" in a or "soundtrack" in a
```

(c) Change the `classify_by_rules` signature to accept `album` and apply the new rules. Replace the function body's matching section so it reads:
```python
def classify_by_rules(genres: list[str], artist: str, titles: list[str],
                      album: str = "") -> RuleResult:
    raw = " ".join((recover_text(g) or "") for g in genres).lower().strip()
    is_korean = bool(_HANGUL.search(artist or "")) or any(_HANGUL.search(t or "") for t in titles)
    has_guitar = any(k in raw for k in ("classical guitar", "클래식기타", "guitar"))

    matched: list[str] = []
    signals: list[str] = []
    for bucket, kws in _RULES:
        hit = next((kw for kw in kws if _kw_matches(kw, raw)), None)
        if hit is None:
            continue
        if bucket == "가요" and not is_korean:
            continue
        matched.append(bucket)
        signals.append(f"{bucket}:{hit}")

    if _has_ost_signal(album) and "경음악_OST" not in matched:
        matched.append("경음악_OST")
        signals.append("album:ost")

    if "클래식" in matched and has_guitar:
        matched = ["클래식기타" if b == "클래식" else b for b in matched]
        signals.append("guitar")
    matched = list(dict.fromkeys(matched))

    # Korean-language popular music is 가요, not western 팝
    if is_korean and matched == ["팝"]:
        matched = ["가요"]
        signals.append("korean->가요")

    if len(matched) == 1:
        return RuleResult(matched[0], 0.9, ";".join(signals))
    if len(matched) > 1:
        chosen = next((b for b in _PRIORITY if b in matched), matched[0])
        return RuleResult(chosen, 0.5, ";".join(signals) + f";multi->{chosen}")
    if is_korean:
        return RuleResult("가요", 0.4, "no-tag;korean->가요")
    return RuleResult(UNCLASSIFIED, 0.0, f"no-tag;raw={raw!r}")
```

In `src/music_wiki/organize/classify.py`, pass the album title — change the `classify_by_rules` call from:
```python
            res = classify_by_rules(album.genres, artist.name, titles)
```
to:
```python
            res = classify_by_rules(album.genres, artist.name, titles, album=album.title)
```

In `src/music_wiki/organize/review.py`, the same change for the signals recomputation — from:
```python
            res = classify_by_rules(album.genres, artist.name, titles)
```
to:
```python
            res = classify_by_rules(album.genres, artist.name, titles, album=album.title)
```

- [ ] **Step 4: Run to verify it passes (and no regression)**

Run: `pytest tests/test_buckets.py tests/test_classify.py tests/test_review.py -v`
Expected: PASS — new bucket tests green; existing M3-A rule/classify/review tests unaffected (the `album` arg defaults to `""`, and the Korean-pop reroute only fires for sole-팝 Korean cases none of the old tests hit).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/buckets.py src/music_wiki/organize/classify.py src/music_wiki/organize/review.py tests/test_buckets.py
git commit -m "feat: L1 refinements — album-title OST, hip-hop/rap, korean-popular->가요"
```

---

### Task 2: MusicBrainz client

**Files:**
- Create: `src/music_wiki/external/__init__.py` (empty), `src/music_wiki/external/musicbrainz.py`
- Test: `tests/test_musicbrainz.py`

**Interfaces:**
- Produces:
  - `MusicBrainzClient` Protocol: `lookup_genres(self, artist: str, album: str) -> list[str]`.
  - `HttpMusicBrainzClient(user_agent: str, *, fetch=None, sleep=None, cache_dir: str | None = None, min_interval: float = 1.0)` — `fetch(url) -> dict` (default uses `requests`), `sleep(seconds)` (default `time.sleep`), both injectable for tests. `lookup_genres` returns the genres+tags of the top release-group match, `[]` on empty input / no match / fetch error; caches results to `cache_dir`; throttles to `min_interval` seconds between fetches.
  - `parse_genres(data: dict) -> list[str]` (module-level, pure) — extracts `genres[].name` + `tags[].name` from the first release-group.

- [ ] **Step 1: Write the failing tests (hermetic — injected fetch, no network)**

`tests/test_musicbrainz.py`:
```python
from music_wiki.external.musicbrainz import HttpMusicBrainzClient, parse_genres

_MB_RESPONSE = {
    "release-groups": [
        {"title": "Waltz for Debby",
         "genres": [{"name": "jazz"}, {"name": "cool jazz"}],
         "tags": [{"name": "piano jazz"}]},
        {"title": "other"},
    ]
}


def test_parse_genres_first_match_only():
    assert parse_genres(_MB_RESPONSE) == ["jazz", "cool jazz", "piano jazz"]
    assert parse_genres({"release-groups": []}) == []
    assert parse_genres({}) == []


def test_lookup_uses_injected_fetch_and_throttles():
    calls = {"fetch": 0, "sleep": []}

    def fake_fetch(url):
        calls["fetch"] += 1
        assert "Waltz" in url and "Bill" in url
        return _MB_RESPONSE

    client = HttpMusicBrainzClient("ua/1.0", fetch=fake_fetch,
                                   sleep=lambda s: calls["sleep"].append(s))
    genres = client.lookup_genres("Bill Evans", "Waltz for Debby")
    assert genres == ["jazz", "cool jazz", "piano jazz"]
    assert calls["fetch"] == 1


def test_lookup_empty_inputs_and_fetch_error_return_empty():
    def boom(url):
        raise RuntimeError("network down")

    client = HttpMusicBrainzClient("ua/1.0", fetch=boom, sleep=lambda s: None)
    assert client.lookup_genres("", "Album") == []        # no fetch attempted
    assert client.lookup_genres("Artist", "Album") == []  # fetch error → []


def test_lookup_caches_to_disk(tmp_path):
    calls = {"n": 0}

    def fake_fetch(url):
        calls["n"] += 1
        return _MB_RESPONSE

    client = HttpMusicBrainzClient("ua/1.0", fetch=fake_fetch, sleep=lambda s: None,
                                   cache_dir=str(tmp_path))
    a = client.lookup_genres("Bill Evans", "Waltz for Debby")
    b = client.lookup_genres("Bill Evans", "Waltz for Debby")   # served from cache
    assert a == b == ["jazz", "cool jazz", "piano jazz"]
    assert calls["n"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_musicbrainz.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.external'`.

- [ ] **Step 3: Implement the client**

Create `src/music_wiki/external/__init__.py` (empty).

`src/music_wiki/external/musicbrainz.py`:
```python
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Protocol


class MusicBrainzClient(Protocol):
    def lookup_genres(self, artist: str, album: str) -> list[str]: ...


def parse_genres(data: dict) -> list[str]:
    """Genres + folksonomy tags of the first (best) release-group match."""
    groups = data.get("release-groups") or []
    if not groups:
        return []
    rg = groups[0]
    names: list[str] = []
    for g in rg.get("genres") or []:
        if g.get("name"):
            names.append(g["name"])
    for t in rg.get("tags") or []:
        if t.get("name"):
            names.append(t["name"])
    return names


class HttpMusicBrainzClient:
    def __init__(self, user_agent: str, *, fetch: Callable[[str], dict] | None = None,
                 sleep: Callable[[float], None] | None = None,
                 cache_dir: str | None = None, min_interval: float = 1.0):
        self._ua = user_agent
        self._fetch = fetch or self._default_fetch
        self._sleep = sleep if sleep is not None else time.sleep
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._min_interval = min_interval
        self._last = 0.0

    def _default_fetch(self, url: str) -> dict:
        import requests

        resp = requests.get(url, headers={"User-Agent": self._ua}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _cache_path(self, artist: str, album: str) -> Path | None:
        if not self._cache_dir:
            return None
        key = hashlib.sha1(f"{artist}|{album}".encode("utf-8")).hexdigest()
        return self._cache_dir / f"mb-{key}.json"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)
        self._last = time.monotonic()

    def lookup_genres(self, artist: str, album: str) -> list[str]:
        if not artist or not album:
            return []
        cache_file = self._cache_path(artist, album)
        if cache_file and cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        self._throttle()
        query = urllib.parse.quote(f'artist:"{artist}" AND releasegroup:"{album}"')
        url = f"https://musicbrainz.org/ws/2/release-group?query={query}&fmt=json&limit=1"
        try:
            data = self._fetch(url)
        except Exception:
            return []
        genres = parse_genres(data)
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(genres, ensure_ascii=False), encoding="utf-8")
        return genres
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_musicbrainz.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/external/__init__.py src/music_wiki/external/musicbrainz.py tests/test_musicbrainz.py
git commit -m "feat: MusicBrainz client (injectable fetch, disk cache, rate-limited)"
```

---

### Task 3: Genre enrichment

**Files:**
- Create: `src/music_wiki/organize/enrich.py`
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: `Store` (`iter_artists`, `albums_for_artist`, `set_album_genre`), `MusicBrainzClient.lookup_genres`, `classify_by_rules`, `UNCLASSIFIED`.
- Produces: `enrich_genres(store: Store, mb_client, *, threshold: float = 0.8) -> int` — for each non-manual album with `confidence < threshold` or bucket in `{None, 미분류}`, look up MusicBrainz genres, run them through `classify_by_rules`, and if the result is a real bucket (`!= 미분류`) with `confidence > current`, write it with `source="musicbrainz"`. Returns the number enriched.

- [ ] **Step 1: Write the failing tests**

`tests/test_enrich.py`:
```python
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.enrich import enrich_genres


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


class FakeMB:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def lookup_genres(self, artist, album):
        self.calls.append((artist, album))
        return self.mapping.get(album, [])


def test_enrich_low_confidence_album():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "Astor Piazzolla", "Tango Zero Hour", "x", ["#JUNK"]))
    classify_albums(s)  # junk → 미분류 (0.0)
    mb = FakeMB({"Tango Zero Hour": ["Tango", "Nuevo Tango"]})
    n = enrich_genres(s, mb)
    assert n == 1
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "제3세계" and album.genre_source == "musicbrainz"


def test_enrich_skips_high_confidence_and_manual():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "Bill Evans", "Waltz", "x", ["Jazz"]))   # high conf
    s.upsert(_rec("/b.mp3", "h2", "VA", "Comp", "y", ["#JUNK"]))           # 미분류
    classify_albums(s)
    comp = next(a for ar in s.iter_artists() for a in s.albums_for_artist(ar.id)
                if a.title == "Comp")
    s.set_album_genre(comp.id, "팝", 1.0, "manual")   # human decision
    mb = FakeMB({"Waltz": ["Bebop"], "Comp": ["Latin"]})
    n = enrich_genres(s, mb)
    assert n == 0                                  # high-conf + manual both skipped
    assert ("Bill Evans", "Waltz") not in mb.calls


def test_enrich_no_genres_leaves_unchanged():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "X", "Y", "t", ["#JUNK"]))
    classify_albums(s)
    mb = FakeMB({})   # no match
    assert enrich_genres(s, mb) == 0
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "미분류"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_enrich.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'music_wiki.organize.enrich'`.

- [ ] **Step 3: Implement enrichment**

`src/music_wiki/organize/enrich.py`:
```python
from __future__ import annotations

from music_wiki.core.store import Store

from .buckets import UNCLASSIFIED, classify_by_rules


def enrich_genres(store: Store, mb_client, *, threshold: float = 0.8) -> int:
    """For non-manual, low-confidence albums, look up MusicBrainz genres and
    re-bucket via the rule mapper. Writes source='musicbrainz' only when the
    looked-up result is a real bucket and more confident than the current one."""
    n = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_source == "manual":
                continue
            conf = album.genre_confidence if album.genre_confidence is not None else 0.0
            if conf >= threshold and album.genre_bucket not in (None, UNCLASSIFIED):
                continue
            mb_genres = mb_client.lookup_genres(artist.name, album.title)
            if not mb_genres:
                continue
            res = classify_by_rules(mb_genres, artist.name, [], album=album.title)
            if res.bucket != UNCLASSIFIED and res.confidence > conf:
                store.set_album_genre(album.id, res.bucket, res.confidence, "musicbrainz")
                n += 1
    return n
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_enrich.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/enrich.py tests/test_enrich.py
git commit -m "feat: MusicBrainz genre enrichment for low-confidence albums"
```

---

### Task 4: Config + CLI `--enrich-genre`

**Files:**
- Modify: `src/music_wiki/core/config.py`, `src/music_wiki/cli.py`
- Test: `tests/test_cli_enrich.py`

**Interfaces:**
- Consumes: `HttpMusicBrainzClient` (Task 2), `enrich_genres` (Task 3), `classify_albums`, `Config`.
- Produces:
  - `Config` gains `musicbrainz_user_agent: str` (default `"music-wiki/0.1 (https://github.com/JiwookJung/music-wiki)"`) and a `mb_cache_dir` property (`vault_dir / "mb-cache"`).
  - `classify` subcommand gains `--enrich-genre` (`action="store_true"`); when set, after L1 it builds an `HttpMusicBrainzClient(cfg.musicbrainz_user_agent, cache_dir=str(cfg.mb_cache_dir))` and runs `enrich_genres`, printing the enriched count. `HttpMusicBrainzClient`/`enrich_genres` are imported at module top so the test can monkeypatch them.

- [ ] **Step 1: Write the failing test (hermetic — monkeypatched client)**

`tests/test_cli_enrich.py`:
```python
from pathlib import Path

from music_wiki.cli import main
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def test_classify_enrich_genre(tmp_path: Path, monkeypatch):
    db = tmp_path / "wiki.db"
    s = Store.open(str(db))
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="Astor Piazzolla", album_title="Tango Zero Hour", track_title="t",
        track_no=1, disc_no=None, year=1986, label=None, genres=["#JUNK"],
        duration_s=60.0, cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    ))

    class FakeMB:
        def lookup_genres(self, artist, album):
            return ["Tango"] if album == "Tango Zero Hour" else []

    monkeypatch.setattr("music_wiki.cli.HttpMusicBrainzClient", lambda *a, **k: FakeMB())

    assert main(["classify", "--db", str(db), "--enrich-genre"]) == 0
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "제3세계" and album.genre_source == "musicbrainz"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_cli_enrich.py -v`
Expected: FAIL — `--enrich-genre` is an unrecognized argument (and `music_wiki.cli.HttpMusicBrainzClient` doesn't exist to patch).

- [ ] **Step 3: Implement config + CLI wiring**

In `src/music_wiki/core/config.py`, add the field and property to the `Config` dataclass:
```python
@dataclass
class Config:
    source_dir: Path
    vault_dir: Path
    db_path: Path
    summary_model: str = "claude-opus-4-8"
    musicbrainz_user_agent: str = "music-wiki/0.1 (https://github.com/JiwookJung/music-wiki)"

    @property
    def mb_cache_dir(self) -> Path:
        return self.vault_dir / "mb-cache"
```
(Keep the existing `default()` classmethod unchanged — the new field has a default and `mb_cache_dir` derives from `vault_dir`.)

In `src/music_wiki/cli.py`, add imports at the top with the others:
```python
from music_wiki.external.musicbrainz import HttpMusicBrainzClient
from music_wiki.organize.enrich import enrich_genres
```

Replace `_cmd_classify` with:
```python
def _cmd_classify(args) -> int:
    cfg = Config.default()
    store = _store_at(args.db)
    n = classify_albums(store)
    print(f"classified {n} albums (rules)")
    if args.enrich_genre:
        client = HttpMusicBrainzClient(cfg.musicbrainz_user_agent,
                                       cache_dir=str(cfg.mb_cache_dir))
        m = enrich_genres(store, client)
        print(f"enriched {m} albums via MusicBrainz")
    return 0
```
(If `Config` isn't already imported in `cli.py`, it is — the existing handlers use `Config.default()` in `main`. Confirm `_cmd_classify` has access; if `cfg` is built in `main`, instead read it there. The existing `main` builds `cfg = Config.default()` and registers subparsers with `cfg`; keep that and just build a fresh `cfg` inside `_cmd_classify` as shown.)

Add the flag to the `classify` subparser registration in `main`:
```python
    p_classify.add_argument("--enrich-genre", action="store_true")
```

- [ ] **Step 4: Run to verify it passes, then full suite + lint**

Run: `pytest tests/test_cli_enrich.py -v`
Expected: PASS.

Run: `pytest -q && ruff check .`
Expected: all tests PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/config.py src/music_wiki/cli.py tests/test_cli_enrich.py
git commit -m "feat: classify --enrich-genre (MusicBrainz) + config"
```

---

### Task 5: Manual verification against MusicBrainz (controller-run)

**Files:** none (manual; live MusicBrainz, read-only on source).

- [ ] **Step 1: Classify a real subtree, then enrich**

```bash
music-wiki scan --source "/mnt/win/memory/음악/melon" --db /tmp/mw-b1.db
music-wiki classify --db /tmp/mw-b1.db
music-wiki classify --db /tmp/mw-b1.db --enrich-genre
```
Expected: first `classify` prints `classified N albums`; the `--enrich-genre` run prints `enriched M albums via MusicBrainz` (M > 0 if any low-confidence albums matched MusicBrainz). No traceback; runs at ~1 req/s.

- [ ] **Step 2: Confirm low-confidence count dropped + cache works**

```bash
music-wiki review-export --db /tmp/mw-b1.db --out /tmp/review-b1.csv --threshold 0.8
wc -l /tmp/review-b1.csv          # expect fewer rows than the pre-enrich M3-A run (~39)
ls "$HOME/music-wiki-vault/mb-cache" 2>/dev/null | head   # cache files written
music-wiki classify --db /tmp/mw-b1.db --enrich-genre   # re-run: served from cache, fast
```
Expected: the review CSV has fewer low-confidence rows than the M3-A baseline (some were resolved by MusicBrainz); `mb-cache/` holds `mb-*.json` files; the re-run is fast (cache hits, no rate-limit waits).

- [ ] **Step 3: Record findings**

Note how many of the ~39 low-confidence albums MusicBrainz resolved and which remain (these feed the M3-B2 LLM backlog). No commit (scratch under `/tmp` and `~/music-wiki-vault/mb-cache`).

---

## Self-Review

**1. Spec coverage** (against M3 organize design §5 L2 + §11 + the M3-B1 scope decision):
- §5 L2 MusicBrainz lookup of low-confidence albums, mapped back through the rule table → Tasks 2–3. ✅
- §11 MusicBrainz default/free, User-Agent, ~1 req/s, disk cache → Task 2 (`HttpMusicBrainzClient` throttle + cache + UA). ✅
- L1 refinements (album-title OST, hip-hop/rap, Korean-popular routing) → Task 1. ✅
- `--enrich-genre` flag (spec §10) → Task 4. ✅
- Discogs / LLM deferred to M3-B2 → out of scope per Global Constraints. ✅
- Hermetic tests (no live calls; fakes behind interfaces) → Tasks 2–4 inject fakes; live only in Task 5. ✅
- Taxonomy unchanged → no bucket added; confirmed. ✅

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — every code step is complete. ✅

**3. Type consistency:** `classify_by_rules(genres, artist, titles, album="")` (Task 1) — the `album` kwarg is used by `classify.py`/`review.py` (Task 1) and `enrich.py` (Task 3) consistently. `MusicBrainzClient.lookup_genres(artist, album) -> list[str]` (Task 2) matches `FakeMB` in Tasks 3–4 and `enrich_genres`'s call. `HttpMusicBrainzClient(user_agent, *, fetch, sleep, cache_dir, min_interval)` (Task 2) matches the CLI construction `HttpMusicBrainzClient(cfg.musicbrainz_user_agent, cache_dir=...)` (Task 4). `enrich_genres(store, mb_client, *, threshold=0.8) -> int` (Task 3) matches the CLI call (Task 4). `Config.mb_cache_dir` / `musicbrainz_user_agent` (Task 4) used in the CLI. `parse_genres(data) -> list[str]` (Task 2) used by `HttpMusicBrainzClient` and tested directly. ✅
