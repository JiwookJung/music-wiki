# 로컬 LLM 계층 (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LM Studio(OpenAI 호환 로컬 LLM, 기본 Qwen3-14B)를 인터페이스 뒤에 붙여 ① MusicBrainz로도 못 잡은 저신뢰 앨범의 L3 장르 분류와 ② 앨범 단위 한국어 해설을 생성해 DB에 저장한다.

**Architecture:** `external/musicbrainz.py`와 동형 패턴(Protocol + 주입형 HTTP fetch + 디스크 캐시 + 레이트리밋)으로 `OpenAICompatibleLLMClient`를 만들고, `enrich_genres`와 동형으로 저신뢰 앨범만 골라 LLM 분류/해설을 수행한다. 단위테스트는 fake fetch/fake client로 라이브 호출 0; 라이브는 별도 수동검증.

**Tech Stack:** Python 3.11, stdlib(`hashlib`, `json`, `time`, `urllib`/`requests`는 기존 의존성 재사용), sqlite3, pytest. 새 런타임 의존성 없음(LM Studio는 외부 프로세스, requests는 이미 사용 중).

## Global Constraints

- 원본 NTFS(`/mnt/win/memory/음악`)는 **읽기 전용**. LLM 산출물(장르 버킷·해설)은 SQLite DB에만 쓴다.
- **로컬 LLM만** 사용(LM Studio OpenAI 호환, 기본 `http://localhost:1234/v1`). 클라우드(Anthropic 등) 호출 금지.
- 외부 호출은 **인터페이스(Protocol) 뒤**에 두고 **fetch 주입**으로 단위테스트는 네트워크 0. 프롬프트 해시 **디스크 캐시**로 재실행 결정적·무비용.
- 분류 대상은 `enrich_genres`와 동일: **`genre_source != 'manual'`** 이고 (`genre_confidence < threshold` 또는 `genre_bucket` ∈ {None, "미분류"}). manual은 절대 덮어쓰지 않음. **더 신뢰도 높을 때만** 기록.
- 7버킷 고정: `BUCKETS = ["클래식","가요","재즈","팝","제3세계","클래식기타","경음악_OST"]`, 폴백 `UNCLASSIFIED = "미분류"`.
- 해설은 **장르·분위기·감상 포인트**로 제한, 연도·인물사 등 사실 단정 금지, **AI 생성 전제**. `description_source = f"llm:{client.model}"`.
- 멱등: classify/describe 재실행 안전. describe는 description이 이미 있으면 skip(단 `force=True`면 재생성).
- LM Studio 미기동/연결 실패는 **보강 단계 실패**로 취급 — 기존 분류/해설 결과를 보존하고 명확히 안내(예외를 호출자에게 전파하되 앨범별로 격리).

---

## File Structure

- **Modify** `src/music_wiki/core/config.py` — `Config`에 `llm_base_url`, `llm_model` 필드 + `llm_cache_dir` property.
- **Create** `src/music_wiki/external/local_llm.py` — `LocalLLMClient`(Protocol) + `OpenAICompatibleLLMClient`.
- **Create** `src/music_wiki/organize/llm_classify.py` — `classify_low_confidence_llm(store, client, *, threshold=0.8)`.
- **Create** `src/music_wiki/organize/describe.py` — `DESCRIBE_SYSTEM` + `describe_albums(store, client, *, force=False, limit=None)`.
- **Modify** `src/music_wiki/cli.py` — `classify`에 `--classify-llm`; 새 `describe` 서브커맨드; config로 클라이언트 구성.
- **Create** `tests/test_config_llm.py`, `tests/test_local_llm.py`, `tests/test_llm_classify.py`, `tests/test_describe.py`, `tests/test_cli_llm.py`.

---

## Task 1: config — LLM 노브

**Files:**
- Modify: `src/music_wiki/core/config.py` (`Config` 7-17, `mb_cache_dir` property 근처)
- Test: `tests/test_config_llm.py`

**Interfaces:**
- Consumes: 기존 `Config` 데이터클래스(`source_dir`, `vault_dir`, `db_path`, `summary_model`, `musicbrainz_user_agent`, `mb_cache_dir` property, `default()` classmethod).
- Produces:
  - `Config.llm_base_url: str = "http://localhost:1234/v1"`
  - `Config.llm_model: str = "qwen3-14b"`
  - `Config.llm_cache_dir` property → `self.vault_dir / "llm-cache"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_llm.py`:

```python
from pathlib import Path

from music_wiki.core.config import Config


def test_llm_defaults_and_cache_dir():
    cfg = Config(source_dir=Path("/src"), vault_dir=Path("/vault"),
                 db_path=Path("/vault/x.db"))
    assert cfg.llm_base_url == "http://localhost:1234/v1"
    assert cfg.llm_model == "qwen3-14b"
    assert cfg.llm_cache_dir == Path("/vault/llm-cache")


def test_llm_fields_overridable():
    cfg = Config(source_dir=Path("/s"), vault_dir=Path("/v"), db_path=Path("/v/x.db"),
                 llm_base_url="http://localhost:5000/v1", llm_model="gemma-3-12b")
    assert cfg.llm_base_url == "http://localhost:5000/v1"
    assert cfg.llm_model == "gemma-3-12b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_llm.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'llm_base_url'` (or AttributeError on `llm_cache_dir`).

- [ ] **Step 3: Implement**

In `src/music_wiki/core/config.py`, add the two fields after `musicbrainz_user_agent` and the property after `mb_cache_dir`:

```python
@dataclass
class Config:
    source_dir: Path
    vault_dir: Path
    db_path: Path
    summary_model: str = "claude-opus-4-8"
    musicbrainz_user_agent: str = "music-wiki/0.1 (https://github.com/JiwookJung/music-wiki)"
    llm_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "qwen3-14b"

    @property
    def mb_cache_dir(self) -> Path:
        return self.vault_dir / "mb-cache"

    @property
    def llm_cache_dir(self) -> Path:
        return self.vault_dir / "llm-cache"
```

(Leave the `default()` classmethod unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_llm.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/core/config.py tests/test_config_llm.py
git commit -m "feat: Config LLM knobs (base_url, model, llm_cache_dir)"
```

---

## Task 2: external/local_llm.py — OpenAI 호환 클라이언트

**Files:**
- Create: `src/music_wiki/external/local_llm.py`
- Test: `tests/test_local_llm.py`

**Interfaces:**
- Consumes: nothing (mirrors `external/musicbrainz.py` structure).
- Produces:
  - `class LocalLLMClient(Protocol)` with attribute `model: str` and method
    `complete(self, system: str, user: str, *, json_schema: dict | None = None) -> str`.
  - `class OpenAICompatibleLLMClient` constructor:
    `__init__(self, base_url: str, model: str, *, fetch: Callable[[str, dict], dict] | None = None, sleep: Callable[[float], None] | None = None, cache_dir: str | None = None, temperature: float = 0.3, min_interval: float = 0.0, timeout: int = 120)`.
  - `.complete(system, user, *, json_schema=None) -> str` returns `choices[0].message.content`. POSTs to `{base_url}/chat/completions`. Caches by `sha1(model|temperature|system|user|json_schema)`. Network exceptions propagate (not cached).
  - `.model` attribute exposing the model id.

- [ ] **Step 1: Write the failing test**

Create `tests/test_local_llm.py`:

```python
import json

from music_wiki.external.local_llm import OpenAICompatibleLLMClient


def _fake_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_complete_builds_payload_and_extracts_content():
    seen = {}

    def fake_fetch(url, payload):
        seen["url"] = url
        seen["payload"] = payload
        return _fake_response("hello")

    client = OpenAICompatibleLLMClient("http://localhost:1234/v1", "qwen3-14b",
                                       fetch=fake_fetch)
    out = client.complete("SYS", "USER")
    assert out == "hello"
    assert seen["url"] == "http://localhost:1234/v1/chat/completions"
    assert seen["payload"]["model"] == "qwen3-14b"
    assert seen["payload"]["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert "response_format" not in seen["payload"]   # no schema → no response_format


def test_complete_passes_json_schema_as_response_format():
    seen = {}

    def fake_fetch(url, payload):
        seen["payload"] = payload
        return _fake_response('{"bucket": "재즈"}')

    client = OpenAICompatibleLLMClient("http://x/v1", "m", fetch=fake_fetch)
    schema = {"type": "object", "properties": {"bucket": {"type": "string"}}}
    out = client.complete("S", "U", json_schema=schema)
    assert json.loads(out) == {"bucket": "재즈"}
    assert seen["payload"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "result", "schema": schema},
    }


def test_complete_caches_by_prompt(tmp_path):
    calls = {"n": 0}

    def fake_fetch(url, payload):
        calls["n"] += 1
        return _fake_response("cached-value")

    client = OpenAICompatibleLLMClient("http://x/v1", "m", fetch=fake_fetch,
                                       cache_dir=str(tmp_path))
    a = client.complete("S", "U")
    b = client.complete("S", "U")   # identical → served from disk cache
    assert a == b == "cached-value"
    assert calls["n"] == 1


def test_complete_does_not_cache_on_fetch_error(tmp_path):
    def boom(url, payload):
        raise RuntimeError("connection refused")

    client = OpenAICompatibleLLMClient("http://x/v1", "m", fetch=boom,
                                       cache_dir=str(tmp_path))
    try:
        client.complete("S", "U")
        assert False, "expected exception to propagate"
    except RuntimeError:
        pass
    assert list(tmp_path.glob("*.json")) == []   # nothing cached
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_local_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'music_wiki.external.local_llm'`.

- [ ] **Step 3: Implement**

Create `src/music_wiki/external/local_llm.py`:

```python
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Protocol


class LocalLLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str, *,
                 json_schema: dict | None = None) -> str: ...


class OpenAICompatibleLLMClient:
    def __init__(self, base_url: str, model: str, *,
                 fetch: Callable[[str, dict], dict] | None = None,
                 sleep: Callable[[float], None] | None = None,
                 cache_dir: str | None = None,
                 temperature: float = 0.3, min_interval: float = 0.0,
                 timeout: int = 120):
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._fetch = fetch or self._default_fetch
        self._sleep = sleep if sleep is not None else time.sleep
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._temperature = temperature
        self._min_interval = min_interval
        self._timeout = timeout
        self._last = 0.0

    def _default_fetch(self, url: str, payload: dict) -> dict:
        import requests

        resp = requests.post(url, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _cache_path(self, key_src: str) -> Path | None:
        if not self._cache_dir:
            return None
        key = hashlib.sha1(key_src.encode("utf-8")).hexdigest()
        return self._cache_dir / f"llm-{key}.json"

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)
        self._last = time.monotonic()

    def complete(self, system: str, user: str, *,
                 json_schema: dict | None = None) -> str:
        key_src = f"{self.model}|{self._temperature}|{system}|{user}|{json_schema}"
        cache_file = self._cache_path(key_src)
        if cache_file and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._temperature,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": json_schema},
            }

        self._throttle()
        data = self._fetch(self._url, payload)   # exceptions propagate, not cached
        content = data["choices"][0]["message"]["content"]
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(content, encoding="utf-8")
        return content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_local_llm.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/external/local_llm.py tests/test_local_llm.py
git commit -m "feat: OpenAICompatibleLLMClient (LM Studio, injectable fetch + disk cache)"
```

---

## Task 3: organize/llm_classify.py — L3 분류

**Files:**
- Create: `src/music_wiki/organize/llm_classify.py`
- Test: `tests/test_llm_classify.py`

**Interfaces:**
- Consumes: `LocalLLMClient.complete(system, user, *, json_schema=None) -> str` (Task 2); `Store.iter_artists()`, `Store.albums_for_artist(id) -> AlbumRow` (`.genres`, `.title`, `.genre_bucket`, `.genre_confidence`, `.genre_source`), `Store.tracks_for_album(id) -> TrackRow(.title)`, `Store.set_album_genre(album_id, bucket, confidence, source)`; `buckets.BUCKETS`, `buckets.UNCLASSIFIED`.
- Produces:
  - `classify_low_confidence_llm(store, client, *, threshold: float = 0.8) -> int` — returns count of albums updated with `source='llm'`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_classify.py`:

```python
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.llm_classify import classify_low_confidence_llm


class FakeLLM:
    model = "fake"

    def __init__(self, content):
        self.content = content
        self.calls = 0

    def complete(self, system, user, *, json_schema=None):
        self.calls += 1
        return self.content


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


def test_llm_updates_low_confidence_album():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", "미상가수", "미상앨범", "곡", ["#JUNK"]))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "미분류", 0.0, "rule")
    llm = FakeLLM('{"bucket": "재즈", "confidence": 0.9, "reasoning": "스윙 편성"}')
    n = classify_low_confidence_llm(s, llm)
    assert n == 1
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "재즈"
    assert album.genre_source == "llm"
    assert album.genre_confidence == 0.9


def test_llm_skips_manual_and_high_confidence():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", "A", "Manual", "t", ["x"]))
    s.upsert(_rec("/x/2.mp3", "h2", "A", "HighConf", "t", ["jazz"]))
    albums = {a.title: a for a in s.albums_for_artist(s.iter_artists()[0].id)}
    s.set_album_genre(albums["Manual"].id, "가요", 1.0, "manual")
    s.set_album_genre(albums["HighConf"].id, "재즈", 0.9, "rule")
    llm = FakeLLM('{"bucket": "팝", "confidence": 0.95, "reasoning": "x"}')
    n = classify_low_confidence_llm(s, llm)
    assert n == 0
    assert llm.calls == 0   # nothing eligible → no LLM call


def test_llm_parse_failure_is_isolated():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", "A", "Alb", "t", ["#JUNK"]))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "미분류", 0.0, "rule")
    llm = FakeLLM("not json at all")
    n = classify_low_confidence_llm(s, llm)   # must not raise
    assert n == 0
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "미분류"   # unchanged


def test_llm_ignores_bucket_not_in_taxonomy():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", "A", "Alb", "t", ["#JUNK"]))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "미분류", 0.0, "rule")
    llm = FakeLLM('{"bucket": "Heavy Metal", "confidence": 0.9, "reasoning": "x"}')
    n = classify_low_confidence_llm(s, llm)
    assert n == 0   # bucket outside the 7 buckets → ignored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'music_wiki.organize.llm_classify'`.

- [ ] **Step 3: Implement**

Create `src/music_wiki/organize/llm_classify.py`:

```python
from __future__ import annotations

import json

from music_wiki.core.encoding import recover_text
from music_wiki.core.store import Store
from music_wiki.external.local_llm import LocalLLMClient

from .buckets import BUCKETS, UNCLASSIFIED

_VALID = set(BUCKETS) | {UNCLASSIFIED}

_SYSTEM = (
    "너는 음악 장르 분류기다. 아래 7개 버킷 중 정확히 하나를 고른다: "
    + ", ".join(BUCKETS)
    + ". 한국 대중음악은 '가요', 영화/드라마/게임 음악은 '경음악_OST', "
    "탱고·라틴·월드뮤직은 '제3세계'. 확신이 없으면 '미분류'."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "bucket": {"type": "string", "enum": BUCKETS + [UNCLASSIFIED]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["bucket", "confidence"],
}


def _prompt(artist: str, album: str, genres: list[str], titles: list[str]) -> str:
    tags = ", ".join((recover_text(g) or "") for g in genres) or "(없음)"
    sample = "; ".join(titles[:8]) or "(없음)"
    return (f"아티스트: {artist}\n앨범: {album}\n장르 태그: {tags}\n"
            f"수록곡 일부: {sample}\n이 앨범의 버킷은?")


def classify_low_confidence_llm(store: Store, client: LocalLLMClient, *,
                                threshold: float = 0.8) -> int:
    n = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_source == "manual":
                continue
            conf = album.genre_confidence if album.genre_confidence is not None else 0.0
            if conf >= threshold and album.genre_bucket not in (None, UNCLASSIFIED):
                continue
            titles = [t.title for t in store.tracks_for_album(album.id)]
            user = _prompt(artist.name, album.title, album.genres, titles)
            try:
                raw = client.complete(_SYSTEM, user, json_schema=_SCHEMA)
                data = json.loads(raw)
                bucket = data["bucket"]
                new_conf = float(data.get("confidence", 0.0))
            except Exception:
                continue   # parse/network failure on one album must not abort the rest
            if bucket not in _VALID or bucket == UNCLASSIFIED:
                continue
            if new_conf > conf:
                store.set_album_genre(album.id, bucket, new_conf, "llm")
                n += 1
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_classify.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/llm_classify.py tests/test_llm_classify.py
git commit -m "feat: classify_low_confidence_llm (L3 LLM genre bucketing)"
```

---

## Task 4: organize/describe.py — 앨범 한국어 해설

**Files:**
- Create: `src/music_wiki/organize/describe.py`
- Test: `tests/test_describe.py`

**Interfaces:**
- Consumes: `LocalLLMClient.complete(system, user) -> str` and `.model` (Task 2); `Store.iter_artists()`, `Store.albums_for_artist(id) -> AlbumRow` (`.title`, `.genres`, `.genre_bucket`, `.description`), `Store.tracks_for_album(id) -> TrackRow(.title)`, `Store.set_album_description(album_id, description, source)` (Phase 1).
- Produces:
  - `DESCRIBE_SYSTEM: str` (the system prompt constant).
  - `describe_albums(store, client, *, force: bool = False, limit: int | None = None) -> int` — count of albums described; writes `set_album_description(id, text.strip(), f"llm:{client.model}")`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_describe.py`:

```python
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.describe import describe_albums


class FakeLLM:
    model = "qwen3-14b"

    def __init__(self, content="  잔잔한 발라드 명반.  "):
        self.content = content
        self.calls = 0
        self.last_user = None

    def complete(self, system, user, *, json_schema=None):
        self.calls += 1
        self.last_user = user
        return self.content


def _rec(path, hash_, artist="이문세", album="3집", title="소녀", genres=None):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=1,
        disc_no=None, year=1987, label=None,
        genres=genres if genres is not None else ["Ballad"], duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_describe_writes_stripped_text_and_source():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    llm = FakeLLM()
    n = describe_albums(s, llm)
    assert n == 1
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description == "잔잔한 발라드 명반."          # stripped
    assert album.description_source == "llm:qwen3-14b"


def test_describe_is_idempotent_unless_force():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    llm = FakeLLM()
    assert describe_albums(s, llm) == 1
    assert describe_albums(s, llm) == 0          # already has description → skip
    assert llm.calls == 1
    assert describe_albums(s, llm, force=True) == 1   # force regenerates
    assert llm.calls == 2


def test_describe_limit_caps_calls():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", artist="A", album="Al1"))
    s.upsert(_rec("/x/2.mp3", "h2", artist="A", album="Al2"))
    llm = FakeLLM()
    n = describe_albums(s, llm, limit=1)
    assert n == 1 and llm.calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_describe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'music_wiki.organize.describe'`.

- [ ] **Step 3: Implement**

Create `src/music_wiki/organize/describe.py`:

```python
from __future__ import annotations

from music_wiki.core.encoding import recover_text
from music_wiki.core.store import Store
from music_wiki.external.local_llm import LocalLLMClient

DESCRIBE_SYSTEM = (
    "너는 음악 큐레이터다. 주어진 메타데이터만으로 한국어 2~4문장의 앨범 소개를 쓴다. "
    "장르·분위기·감상 포인트 중심으로 서술하고, 발매연도·인물사·수상 등 확인 불가한 "
    "사실은 단정하지 않는다. 모르면 추측하지 말고 음악적 인상만 쓴다. "
    "머리말이나 따옴표 없이 본문만 출력한다."
)


def _prompt(artist: str, album: str, bucket: str | None, genres: list[str],
            titles: list[str]) -> str:
    tags = ", ".join((recover_text(g) or "") for g in genres) or "(없음)"
    sample = "; ".join(titles[:8]) or "(없음)"
    return (f"아티스트: {artist}\n앨범: {album}\n장르 버킷: {bucket or '미정'}\n"
            f"장르 태그: {tags}\n수록곡 일부: {sample}\n이 앨범을 한국어로 소개해줘.")


def describe_albums(store: Store, client: LocalLLMClient, *,
                    force: bool = False, limit: int | None = None) -> int:
    n = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if limit is not None and n >= limit:
                return n
            if album.description and not force:
                continue
            titles = [t.title for t in store.tracks_for_album(album.id)]
            user = _prompt(artist.name, album.title, album.genre_bucket,
                           album.genres, titles)
            try:
                text = client.complete(DESCRIBE_SYSTEM, user)
            except Exception:
                continue   # per-album isolation: one failure does not abort the rest
            text = (text or "").strip()
            if not text:
                continue
            store.set_album_description(album.id, text, f"llm:{client.model}")
            n += 1
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_describe.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/music_wiki/organize/describe.py tests/test_describe.py
git commit -m "feat: describe_albums (local-LLM Korean album notes, idempotent)"
```

---

## Task 5: CLI — `classify --classify-llm` + `describe`

**Files:**
- Modify: `src/music_wiki/cli.py` (imports 7-17, `_cmd_classify` 42-52, `main` 파서 등록)
- Test: `tests/test_cli_llm.py`

**Interfaces:**
- Consumes: `classify_low_confidence_llm(store, client, *, threshold=0.8)` (Task 3), `describe_albums(store, client, *, force=False, limit=None)` (Task 4), `OpenAICompatibleLLMClient(base_url, model, *, cache_dir=...)` (Task 2), `Config` LLM fields (Task 1), existing `_store_at`, `classify_albums`, `enrich_genres`, `HttpMusicBrainzClient`.
- Produces:
  - `classify` gains `--classify-llm` flag → after rules (and optional MB enrich) runs `classify_low_confidence_llm`.
  - New `describe` subcommand (`--db`, `--force`, `--limit`) → `_cmd_describe`.
  - A helper `_llm_client(cfg)` building `OpenAICompatibleLLMClient` from config.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_llm.py`:

```python
from pathlib import Path

import music_wiki.cli as cli
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


class FakeLLM:
    model = "fake-model"

    def complete(self, system, user, *, json_schema=None):
        # classify path asks for json; describe path asks for prose
        if json_schema is not None:
            return '{"bucket": "재즈", "confidence": 0.95, "reasoning": "스윙"}'
        return "한국어 해설 본문."


def _seed(db: Path):
    s = Store.open(str(db))
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="미상", album_title="미상앨범", track_title="곡", track_no=1,
        disc_no=None, year=2000, label=None, genres=["#JUNK"], duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    ))


def test_classify_llm_flag_invokes_llm(tmp_path, monkeypatch):
    db = tmp_path / "w.db"
    _seed(db)
    monkeypatch.setattr(cli, "_llm_client", lambda cfg: FakeLLM())
    assert cli.main(["classify", "--db", str(db), "--classify-llm"]) == 0
    s = Store.open(str(db))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "재즈" and album.genre_source == "llm"


def test_describe_command_writes_description(tmp_path, monkeypatch):
    db = tmp_path / "w.db"
    _seed(db)
    monkeypatch.setattr(cli, "_llm_client", lambda cfg: FakeLLM())
    assert cli.main(["describe", "--db", str(db)]) == 0
    s = Store.open(str(db))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description == "한국어 해설 본문."
    assert album.description_source == "llm:fake-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_llm.py -v`
Expected: FAIL — `test_classify_llm_flag_invokes_llm` fails on `invalid choice`/missing `_llm_client` attr; `describe` is an invalid subcommand.

- [ ] **Step 3: Implement**

In `src/music_wiki/cli.py`, add imports (near the other organize imports):

```python
from music_wiki.external.local_llm import OpenAICompatibleLLMClient
from music_wiki.organize.llm_classify import classify_low_confidence_llm
from music_wiki.organize.describe import describe_albums
```

Add a client-builder helper (after `_store_at`):

```python
def _llm_client(cfg: Config) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(cfg.llm_base_url, cfg.llm_model,
                                     cache_dir=str(cfg.llm_cache_dir))
```

Replace `_cmd_classify` to add the LLM stage:

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
    if args.classify_llm:
        k = classify_low_confidence_llm(store, _llm_client(cfg))
        print(f"classified {k} low-confidence albums via local LLM")
    return 0
```

Add the `describe` handler (after `_cmd_classify`):

```python
def _cmd_describe(args) -> int:
    cfg = Config.default()
    store = _store_at(args.db)
    n = describe_albums(store, _llm_client(cfg), force=args.force, limit=args.limit)
    print(f"described {n} albums via local LLM ({cfg.llm_model})")
    return 0
```

In `main`, add the `--classify-llm` flag to the existing classify parser:

```python
    p_classify.add_argument("--classify-llm", action="store_true")
```

And register the `describe` subparser (after the classify parser):

```python
    p_describe = sub.add_parser("describe", help="앨범 한국어 해설 생성(로컬 LLM) → DB")
    p_describe.add_argument("--db", default=str(cfg.db_path))
    p_describe.add_argument("--force", action="store_true")
    p_describe.add_argument("--limit", type=int, default=None)
    p_describe.set_defaults(func=_cmd_describe)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_llm.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run full suite + lint**

Run: `pytest -q && ruff check src tests`
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/music_wiki/cli.py tests/test_cli_llm.py
git commit -m "feat: classify --classify-llm + describe CLI (local LLM)"
```

---

## Self-Review (완료)

**Spec coverage (§5):** §5.1 config 노브→Task 1 / §5.2 OpenAICompatibleLLMClient(Protocol·주입 fetch·캐시·response_format)→Task 2 / §5.3 classify_low_confidence_llm(저신뢰만·manual 스킵·json_schema·정규버킷 매핑·예외격리·더 신뢰도일 때만)→Task 3 / §5.4 describe_albums(DESCRIBE_SYSTEM·멱등·force·source=llm:model)→Task 4 / §6 CLI(`--classify-llm`+`describe`)→Task 5. §8 안전·멱등·LM Studio 실패 격리→Global Constraints + Task 3/4 try/except + Task 5 `_llm_client` 주입(테스트 monkeypatch).

**Placeholder scan:** 모든 step에 실제 코드/명령/기대출력 포함. 모호 표현 없음.

**Type consistency:** `complete(system, user, *, json_schema=None) -> str` 시그니처가 Task 2 정의 = Task 3/4 호출 = Task 5 FakeLLM 일치. `classify_low_confidence_llm(store, client, *, threshold=0.8)` = Task 3 정의 = Task 5 호출 일치. `describe_albums(store, client, *, force, limit)` = Task 4 정의 = Task 5 호출 일치. `_llm_client(cfg)` = Task 5 정의 = 테스트 monkeypatch 대상 일치. `set_album_genre(id, bucket, conf, source)`/`set_album_description(id, text, source)` = Phase 1 store 시그니처 일치. `BUCKETS`/`UNCLASSIFIED`/`recover_text`/`RuleResult`는 기존 모듈 그대로 import.

**라이브 의존성:** 단위테스트는 전부 fake fetch/fake client/monkeypatch로 네트워크 0. LM Studio 실제 호출은 구현 외 수동검증(별도) — 계획 태스크에 포함하지 않음.
