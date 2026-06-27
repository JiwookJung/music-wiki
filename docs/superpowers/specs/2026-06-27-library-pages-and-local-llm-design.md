# music-wiki M3-C/M3-B2 — 라이브러리 페이지 + 로컬 LLM(분류·해설) 설계

- 상태: 승인됨 (설계 문서).
- 작성일: 2026-06-27
- 의존: M1(core + ingest/audio), M3-A(organize: classify/plan/apply), M3-B1(MusicBrainz enrich) 위에 구축.
- 관련: `2026-06-27-music-library-organize-design.md`(이 문서가 그 §5 L3·§11의 "Claude"를 **로컬 LLM**으로 대체).

## 1. 목표 / 비목표

### 목표
1. **정리된 라이브러리(`organize --apply` 산출 트리)의 각 앨범 폴더 안에 자체 완결형 `index.html`을 생성**한다. 같은 폴더의 오디오를 재생하면서 앨범/곡 정보와 해설을 한 화면에서 본다(설명을 읽으며 듣기). 더블클릭(`file://`)으로 열리고 외부 서버·의존성이 없다.
2. **로컬 LLM(LM Studio, OpenAI 호환 API)** 계층을 인터페이스 뒤에 추가해, ① MusicBrainz로도 못 잡은 저신뢰 앨범의 **L3 장르 분류**와 ② **앨범 단위 한국어 해설** 생성을 수행한다. 해설은 DB에 저장되고 페이지에 표시된다.

### 비목표
- 원본 NTFS 수정·이동·태그 재기록(읽기 전용 — 복사만). 페이지·해설은 `/home`의 정리 트리/DB에만 쓴다.
- 오디오 재인코딩·트랜스코딩. `<audio>`는 원본 코덱을 브라우저가 지원하는 범위에서 재생(미지원 코덱은 브라우저 한계).
- 곡별(track-level) 해설(이번 범위 밖 — 앨범 단위만). 환각 최소화가 우선.
- 클라우드 LLM(Anthropic 등) 호출. **로컬 LLM만** 사용.
- 라이브러리 전역을 묶는 서버형 웹앱(그것은 M4).

## 2. 컨텍스트

- `organize --apply`가 `source_file.organized_path`에 각 곡의 복사 목적지 절대경로를 기록한다(M3-A). 앨범 폴더 = 그 경로들의 공통 부모.
- LM Studio는 OpenAI 호환 서버(기본 `http://localhost:1234/v1`)로 동작. 하드웨어: RTX 5060 Ti 16GB + RTX 3060 12GB. 기본 모델 **Qwen3-14B**(config 노브로 교체 가능: Gemma 3, Qwen3-30B-A3B 등). 오프라인 배치라 지연 비중요.
- **환각 위험**: 무명 한국 음반의 사실(연도·인물사)을 LLM이 지어낼 수 있음 → 해설은 장르·분위기·감상포인트로 제한하고 AI 생성임을 표기.

## 3. 아키텍처

M1/M3 패턴(인터페이스 뒤 외부 클라이언트 + 주입형 fetch + 디스크 캐시 + 멱등 + 비파괴 마이그레이션)을 그대로 재사용. 두 빌드 단계로 나눈다.

```
src/music_wiki/
  organize/pages.py        앨범(정리된 파일들) → index.html 렌더(자체완결, file:// 동작)
  organize/describe.py     앨범 → 한국어 해설(LocalLLMClient) → DB
  organize/llm_classify.py 저신뢰 앨범 → L3 장르(LocalLLMClient) → DB
  external/local_llm.py    LocalLLMClient(Protocol) + OpenAICompatibleLLMClient
  core/store.py            + iter_organized() 읽기, description 컬럼, set_album_description()
  core/config.py           + llm_base_url, llm_model, llm_cache_dir
  cli.py                   + build-pages, describe; classify에 --classify-llm
```

### 데이터 흐름
```
scan → DB → classify(규칙) →[--enrich-genre] MusicBrainz →[--classify-llm] 로컬LLM L3
   → review(CSV 왕복, 선택) → organize --apply(복사 + organized_path 기록 + 페이지 생성)
   → describe(로컬LLM 해설 → DB) → build-pages(해설 포함 재렌더)
```

## 4. Phase 1 — 라이브러리 페이지 (LLM 불필요, 먼저)

LM Studio 없이도 오늘 검증 가능한 완결 슬라이스. 메타+트랙리스트로 먼저 동작하고, 해설은 있으면 표시(없으면 섹션 생략).

### 4.1 store 확장
- 비파괴 마이그레이션(`_migrate`)에 컬럼 추가: `album.description TEXT`, `album.description_source TEXT`. (Phase 1에서 추가해 두고, Phase 2가 채운다.)
- `AlbumRow`에 `description`, `description_source` 필드 추가 + `albums_for_artist` SELECT에 반영.
- 새 읽기:
  ```python
  @dataclass
  class OrganizedRow:
      organized_path: str          # 복사된 파일의 절대경로
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

  def iter_organized(self) -> list[OrganizedRow]:
      # source_file(organized_path IS NOT NULL AND is_drm=0)
      #   JOIN track JOIN album JOIN artist
      # ORDER BY ar.name, al.title, t.disc_no, t.track_no
  ```
  앨범 폴더 = `os.path.dirname(organized_path)`. 같은 폴더로 묶이는 행들이 한 앨범의 트랙 목록.
- 새 쓰기: `set_album_description(self, album_id: int, description: str, source: str) -> None`.

### 4.2 pages.py
```python
def build_library_pages(store: Store, *, dry_run: bool = False) -> int:
    """organized_path가 있는 곡들을 앨범 폴더별로 묶어 각 폴더에 index.html을 쓴다.
    파생물이라 항상 덮어쓴다(멱등). 반환=쓴 페이지 수. dry_run이면 쓰지 않고 셈만."""
```
- `store.iter_organized()`를 `dirname(organized_path)`로 그룹핑. 각 그룹 = 한 앨범 폴더.
- 그룹의 첫 행에서 앨범 헤더(아티스트·앨범·연도·버킷·해설)를, 행들에서 트랙 목록을 만든다. `src` = `basename(organized_path)`(상대경로, JS에서 `encodeURIComponent`).
- 폴더가 실제로 존재할 때만 쓴다(apply 이후). 없으면 skip(셈에서 제외).
- 렌더 순수함수 분리:
  ```python
  def render_album_html(*, artist: str, album: str, year: int | None, bucket: str | None,
                        description: str | None, tracks: list[dict]) -> str
  # tracks[i] = {"src": basename, "label": "1-07 소녀", "title": str, "duration_s": float|None}
  ```

### 4.3 index.html 구성 (자체 완결, 의존성 0)
- `<!doctype html>` + 인라인 `<style>` + 인라인 `<script>`. 외부 CDN/네트워크 없음.
- **헤더**: `아티스트 — 앨범 (연도)`, 장르 버킷 배지.
- **플레이어**: `<audio controls>` 1개 + 트랙 **플레이리스트**(ol). 트랙 클릭 → `audio.src = encodeURIComponent(basename)` 후 재생, 현재 곡 하이라이트, 끝나면 다음 곡 자동(설명 읽으며 듣기에 최적). 트랙 데이터는 `<script>` 안 JSON 배열로 인라인.
- **해설 패널**: `description`이 있으면 표시 + "🤖 AI 생성(장르·분위기 기준, 사실 검증 안 됨)" 주석. 없으면 섹션 자체를 생략.
- **DRM 주석**: 해당 앨범에 DRM 곡이 있으면(별도 조회) "재생불가(DRM) N곡" 한 줄. v1은 카운트만(선택, 생략 가능).
- **푸터**: 생성 시각·도구명. 모든 사용자 텍스트(아티스트/앨범/곡/해설)는 HTML 이스케이프, `src`는 URL 인코딩.

### 4.4 CLI / 연결
- 새 명령: `music-wiki build-pages [--db ...] [--dry-run]` → `build_library_pages(store, dry_run=...)`. (대상 폴더는 DB의 organized_path가 지시하므로 `--target` 불필요.)
- `organize --apply`는 복사 성공 후 끝에서 `build_library_pages(store)`를 자동 호출(복사 직후 폴더에 페이지가 바로 생김). dry-run organize는 페이지를 만들지 않음.

## 5. Phase 2 — 로컬 LLM 계층 (분류 + 해설)

### 5.1 config 확장
```python
llm_base_url: str = "http://localhost:1234/v1"
llm_model: str = "qwen3-14b"          # LM Studio에 로드된 모델 id로 교체
@property
def llm_cache_dir(self) -> Path:      # self.vault_dir / "llm-cache"
```

### 5.2 external/local_llm.py (musicbrainz.py와 동형)
```python
class LocalLLMClient(Protocol):
    model: str
    def complete(self, system: str, user: str, *, json_schema: dict | None = None) -> str: ...

class OpenAICompatibleLLMClient:
    def __init__(self, base_url: str, model: str, *,
                 fetch: Callable[[str, dict], dict] | None = None,   # (url, json_payload) -> response dict
                 sleep: Callable[[float], None] | None = None,
                 cache_dir: str | None = None,
                 temperature: float = 0.3, min_interval: float = 0.0, timeout: int = 120):
        ...
    def complete(self, system, user, *, json_schema=None) -> str:
        # payload = {"model", "messages":[{role:system},{role:user}], "temperature",
        #            ("response_format": {"type":"json_schema","json_schema":{...}}) if json_schema}
        # cache key = sha1(f"{model}|{temperature}|{system}|{user}|{json_schema}")
        # POST f"{base_url}/chat/completions" via fetch; return choices[0].message.content
        # 캐시 히트 시 호출 안 함. 네트워크 예외는 호출자에게 전파(캐시에 안 씀).
```
- `_default_fetch(url, payload)`는 `requests.post(url, json=payload, timeout=...)`.
- 단위테스트는 `fetch` 주입(라이브 호출 0). 디스크 캐시로 재실행 결정적·무비용.

### 5.3 llm_classify.py (L3 분류)
```python
def classify_low_confidence_llm(store: Store, client: LocalLLMClient, *,
                                threshold: float = 0.8) -> int:
    """enrich_genres와 동일한 대상 선정(비 manual, confidence<threshold 또는 미분류).
    LLM에 아티스트·앨범·복구 장르태그·트랙명 일부 + 7버킷 목록을 주고 1택 강제.
    더 신뢰도 높을 때만 set_album_genre(..., 'llm')."""
```
- json_schema로 출력 강제: `{"bucket": <BUCKETS+UNCLASSIFIED enum>, "confidence": number(0~1), "reasoning": str}`.
- 응답 bucket을 정규 버킷 문자열로 매핑(미스매치/파싱실패 → 해당 앨범 skip, 예외 격리). `res.confidence > 현재`일 때만 기록.
- `classify --classify-llm`에서 호출. enrich(MusicBrainz) 다음 단계로 동작(MB가 못 잡은 잔여 대상).

### 5.4 describe.py (앨범 해설)
```python
DESCRIBE_SYSTEM = (
    "너는 음악 큐레이터다. 주어진 메타데이터만으로 한국어 2~4문장의 앨범 소개를 쓴다. "
    "장르·분위기·감상 포인트 중심으로 서술하고, 발매연도·인물사·수상 등 확인 불가한 "
    "사실은 단정하지 않는다. 모르면 추측하지 말고 음악적 인상만 쓴다."
)

def describe_albums(store: Store, client: LocalLLMClient, *,
                    force: bool = False, limit: int | None = None) -> int:
    """description이 비었거나 force면 LLM 해설 생성 → set_album_description(.., f'llm:{client.model}').
    멱등(있으면 skip). 예외는 앨범별 격리(한 건 실패가 전체 중단 안 함)."""
```
- 입력 프롬프트: 아티스트, 앨범, 버킷, 복구 장르태그, 트랙명 일부(상위 N개). schema 없음(자유 한국어 텍스트), 결과 `strip()` 저장.
- `music-wiki describe [--db ...] [--force] [--limit N]`. 생성 후 `build-pages` 재실행으로 페이지에 반영(안내 출력).

## 6. CLI (요약)
```
music-wiki classify     [--enrich-genre] [--classify-llm]   # 규칙 → MB → 로컬LLM
music-wiki describe     [--force] [--limit N]               # 앨범 해설 → DB
music-wiki organize     [--target ...] [--apply]            # 복사(+apply 시 페이지 자동생성)
music-wiki build-pages  [--dry-run]                         # 앨범 폴더에 index.html (재)생성
```
`--classify-llm`/`describe`는 `Config`로 `OpenAICompatibleLLMClient(cfg.llm_base_url, cfg.llm_model, cache_dir=cfg.llm_cache_dir)`를 구성해 주입. LM Studio 미기동 시 연결 예외 → 명확한 안내 후 종료(분류/해설은 보강 단계라 실패해도 기존 결과 보존).

## 7. 테스트
- **pages**: 인메모리 Store에 곡 2개(같은 앨범, organized_path를 임시폴더로) 세팅 → `build_library_pages` → 각 폴더에 index.html 존재, 트랙 basename(인코딩)·이스케이프된 아티스트/앨범 포함, 멱등(재실행 동일). description 있을 때 패널 표시·없을 때 섹션 생략. 디스크 외 라이브러리 비의존.
- **render_album_html**: 순수함수 — 특수문자(`<`, `&`, 따옴표) 이스케이프, 해설 유무 분기, 외부 URL 0(네트워크 미참조) 단언.
- **local_llm**: fake fetch가 정해진 dict 반환 → payload 형태(model·messages·response_format 유무), content 추출, 캐시 히트 시 fetch 미호출, json_schema 전달 검증. 라이브 0.
- **llm_classify**: fake client가 버킷 JSON 반환 → 저신뢰만 갱신·manual 스킵·source='llm', 파싱실패 격리.
- **describe**: fake client가 텍스트 반환 → set_album_description, 멱등 skip, `--force` 재생성.
- **라이브 검증(수동 태스크)**: LM Studio + Qwen3 기동 후 데모 DB에 `classify --classify-llm`/`describe`/`build-pages` 실행 → 브라우저로 index.html 열어 재생·해설 육안 확인.

## 8. 안전 · 멱등 · 엣지
- 원본 불변. 페이지·해설은 `/home` 정리 트리/DB에만. build-pages/describe/classify 모두 재실행 안전.
- `file://` 제약: 로컬 파일 `fetch` 불가 → 데이터는 HTML에 인라인, 오디오는 `<audio src="상대경로">`로 회피(인라인 fetch 안 씀).
- DRM 곡: organized_path 없음(미복사) → 플레이리스트에서 자동 제외. (선택) 앨범에 DRM 곡 있으면 카운트만 표기.
- LLM 환각: 해설 시스템 프롬프트로 사실 단정 금지 + 페이지에 AI 생성 표기. 해설은 정보가 아니라 인상으로 취급.
- 미지원 코덱: 브라우저가 못 여는 포맷은 재생 불가(트랜스코딩 비목표) — 페이지엔 트랙으로 남되 재생만 안 됨.

## 9. 구현 단계 (별도 plan)
- **Phase 1 (페이지·선)**: description 컬럼 마이그레이션 → `iter_organized`/`set_album_description` → `render_album_html` → `build_library_pages` → `build-pages` CLI + organize 자동연결. **LLM 없이 완결·검증.**
- **Phase 2 (로컬 LLM·후)**: config 노브 → `OpenAICompatibleLLMClient` → `llm_classify` + `--classify-llm` → `describe` + CLI → (재)build-pages로 해설 반영.

각 단계는 별도 writing-plans → subagent-driven 구현 사이클.
