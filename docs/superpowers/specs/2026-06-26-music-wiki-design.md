# music-wiki 설계 (core + ingest/audio + ingest/lp)

- 상태: 승인됨 (설계 문서). 구현은 마일스톤 단계화.
- 작성일: 2026-06-26
- 범위: 통합 1건. 구현 단계 = M1(core + audio) → M2(lp).

## 1. 목표와 비목표

### 목표
저장된 mp3 등 음악 라이브러리와 LP 컬렉션을 하나의 지식베이스로 정리하고, **LLM 기반 마크다운 위키**(아티스트 / 앨범 / 트랙)로 만든다. 로컬·외부 비노출.

### 비목표 (v1)
- neo4j 등 그래프 DB (관계 질의가 실제로 필요해지면 그때).
- 웹 서비스·인증·멀티유저.
- 원본 파일 수정·이동·태그 재기록 (원본은 **읽기 전용**, 절대 변경 안 함).
- `.enc`(Melon DRM) 복호화·재생.

## 2. 데이터 소스 (실측, 읽기 전용)

`/mnt/win/memory/음악` — `/dev/sdb2` ntfs3, 동시 읽기 안전.

- 오디오 **15,305개**: mp3 14,247 · flac 322 · ape 233 · ogg 231 · wav 112 · m4a 100 · wma 60.
- 부속물: jpg 828(loose 아트) · pdf 823 · `.enc` 422(DRM, 기록만) · gp3~5(기타 탭) · cue 24 · m3u 27.
- 구조: 최대 8단계 중첩, 혼재된 네이밍(flat `melon/`의 `아티스트-NN-제목.mp3`, 중첩 앨범 폴더, `토이3/4/5` 등).
- ID3 채움률(40개 표본): title ~93% · artist/album ~88% · genre ~90% · **year ~65%** · 임베디드 아트 ~18%.

### 식별된 리스크
1. **인코딩**: 구 국내 mp3는 ID3를 CP949/EUC-KR로 저장하고 Latin-1로 라벨링 → 단순 디코딩 시 mojibake. 전용 디코더 필요.
2. **엔티티 해소**: 폴더·태그 양쪽이 불규칙 → 트랙을 앨범/아티스트로 묶는 것이 최난점.

## 3. 아키텍처

```
core/            엔티티 모델 · SQLite 저장소 · 정규화/엔티티해소 · 인코딩 유틸 · 위키 생성기 · config
ingest/audio/    스캔 → 태그 읽기 → 디코딩 → 정규화 → 엔티티 매핑 → (선택)보강/요약   [M1]
ingest/lp/       비전-LLM 책등 인식 → Discogs 정규화 → mp3 대조 → 검증 UI            [M2]
cli/             진입점: scan / build-wiki / enrich / summarize / lp ...
tests/           픽스처 기반 단위테스트
```

원칙: 각 모듈은 한 가지 책임. audio/lp는 `core`의 **저장소·모델 인터페이스에만** 의존하고 서로를 모른다. DB가 단일 진실원천(SSOT)이고 위키 md는 DB에서 생성되는 산출물(언제든 재생성).

### 스택
- Python 3.11 (CI 기존 설정 일치). 의존성: `mutagen`(태그), `ffprobe`(폴백), `Pillow`(아트), `anthropic`(요약), 표준 `sqlite3`. requirements.txt에 추가, CI 엄격화(`ruff` `|| true` 제거).

## 4. 데이터 모델 (SQLite)

```
artist(id, name, sort_name, mbid?, summary_md?, summary_model?, summary_at?)
album(id, title, primary_artist_id, year?, label_id?, mbid?,
      has_digital BOOL, has_vinyl BOOL,         -- 소장형태 플래그 (LP↔mp3 연결)
      summary_md?, summary_model?, summary_at?)
track(id, album_id, disc_no?, track_no?, title, duration_s?, mbid?)
label(id, name)
genre(id, name)                                  -- album_genre / artist_genre N:M
album_artist(album_id, artist_id, role)          -- V.A./피처링 대응
source_file(id, track_id?, abs_path, content_hash, mtime, format,
            decode_status, is_drm BOOL)          -- 멱등·출처추적; 원본 절대 불변
art_asset(id, owner_type, owner_id, kind, abs_path|blob_ref)
```

- 멱등 키 = `source_file.content_hash`. 재실행 시 변경 파일만 upsert.
- `has_vinyl`/`has_digital`는 audio가 디지털을, lp가 바이닐을 세팅 → 교집합이 "둘 다 보유".

## 5. audio 파이프라인 (M1)

1. **스캔**: 읽기전용 walk → 오디오 열거. `.enc`는 `is_drm=true`로 기록만(위키에 "DRM, 재생불가" 표기).
2. **태그 읽기**: mutagen 우선, 실패 시 ffprobe 폴백. 인터페이스 `TagReader` 뒤로 감싸 테스트 가능하게.
3. **디코딩**: 바이트열 휴리스틱으로 CP949/EUC-KR mojibake 감지·재디코딩. `decode_status` 기록(`ok|recovered|suspect`).
4. **정규화**: artist/album/title 트림·케이스·괄호표기 정리(예: `(feat. …)` 분리).
5. **엔티티 해소**: **태그 우선**(normalized artist+album) → 동일 키면 같은 앨범. 태그 부실 시 **폴더 경로를 폴백 힌트**로. 휴리스틱은 `EntityResolver`로 분리해 케이스별 단위테스트.
6. **아트**: 임베디드 추출 → 없으면 같은 폴더 `cover.*`/`folder.*`/loose jpg 참조.
7. **저장**: SQLite upsert(`content_hash` 키), `album.has_digital=true`.
8. **(선택) 보강**: MusicBrainz로 mbid/연도/레이블 보강. **기본 off**(15k 레이트리밋 부담). `--enrich` 플래그, 캐시 디렉토리에 응답 캐싱.
9. **(선택) 요약**: §7 참조. 기본 off.
10. **위키 생성**: DB → md. 아티스트/앨범/트랙 페이지, `[[링크]]`, 보유형태 배지, 아트, (있으면)요약.

## 6. lp 파이프라인 (M2) — 사용자 확정 5단계

입력: 선반 한 줄 = 사진 한 장, 책등 세로 고해상도(샘플 `/mnt/win/memory/음악/lp`, 5472×3648, 4장).

1. **자동 인식**: 비전 LLM(Claude, 이미지 입력)이 좌→우 순서로 읽히는 제목을 **위치+신뢰도**와 함께 추출.
2. **보완**: 어렵/실패 항목은 사용자가 재촬영(더 적은 장수·또렷) 또는 수동 제목 입력.
3. **정규화**: Discogs/MusicBrainz 매칭(레이블·카탈로그번호 단서 활용).
4. **mp3 대조**: 인식 앨범을 audio 라이브러리(SQLite)와 매칭 → `album.has_vinyl=true`.
5. **검증 UI**: 크롭된 책등 이미지 + 추정 제목 확인/수정 → 위키 확정.

현실: 또렷한 책등(클래식 등)↑, 얇고 빽빽한 국내반↓ → **부분 카탈로그 + 보완** 전제. UI 형태(로컬 웹/CLI)는 M2 진입 시 별도 설계.

## 7. LLM 요약 모듈

- **단위**: **앨범·아티스트만** (트랙 15k개 요약은 낭비·저가치). 입력 = 정규화 엔티티 + (있으면)MusicBrainz 사실.
- **제공자**: Claude (Anthropic SDK). 모델은 config 노브, 기본 `claude-opus-4-8`.
  - 대량 배치 비용 절감 시 사용자가 `claude-haiku-4-5`(\$1/\$5) 또는 `claude-sonnet-4-6`(\$3/\$15)로 설정 가능.
  - **Batch API**(50% 비용, 비실시간 적합)와 **prompt caching**(공유 시스템 프롬프트) 사용.
- **프롬프트**: 사실 기반 짧은 해설 생성, 환각 억제(모르면 비움). 결과는 `summary_md` + `summary_model`/`summary_at` 기록 → 재실행 시 미변경 엔티티 건너뜀.
- 기본 off. `--summarize [--scope album|artist]`로 단계 실행.

## 8. CLI

```
music-wiki scan       [--enrich] [--summarize]   # 스캔→DB (멱등)
music-wiki build-wiki [--out DIR]                # DB→마크다운 위키
music-wiki enrich     [--source musicbrainz]     # 외부 보강만
music-wiki summarize  [--scope album|artist]     # 요약만
music-wiki lp ...                                # M2
```

위키 출력: `/home`의 **재생성 가능한 별도 vault 디렉토리**(기본 `~/music-wiki-vault/`, config로 변경). 기존 `~/Obsidian Vault`엔 직접 쓰지 않음(안전·idempotent; 심볼릭 링크/오픈으로 연계 가능).

## 9. 테스트 전략

- 픽스처: 정상/모지바케 ID3 mp3, 임베디드 아트 유무, V.A. 앨범, 동일 앨범 다중 폴더.
- 단위테스트: 인코딩 디코더(케이스 테이블), `EntityResolver`(그룹핑 케이스), 위키 렌더(스냅샷).
- `TagReader`/`MusicBrainzClient`/`LLMClient`는 인터페이스 뒤로 감싸 외부 호출 없이 테스트.
- CI: `ruff check .` 엄격화, `pytest -q`.

## 10. 구현 마일스톤

- **M1 core + audio**: 모델·저장소 → 스캔/디코딩/해소 → 위키 생성. (보강·요약은 플래그, 후속 채움)
- **M2 lp**: 비전 인식 → Discogs 정규화 → mp3 대조 → 검증 UI.

각 마일스톤은 별도 writing-plans → 구현 사이클.
