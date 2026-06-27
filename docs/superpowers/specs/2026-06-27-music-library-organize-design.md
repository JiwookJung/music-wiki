# music-wiki M3 — 라이브러리 정리(organize) 설계

- 상태: 승인됨 (설계 문서).
- 작성일: 2026-06-27
- 의존: M1(core + ingest/audio) 위에 구축. M2(lp)와 독립.

## 1. 목표 / 비목표

### 목표
M1이 만든 엔티티 DB를 바탕으로, 읽기전용 음악 라이브러리를 **장르별로 분류해 `/home`의 정리된 라이브러리로 복사·재배치**한다. 폴더 구조 = **장르 / 아티스트 / 앨범 / 곡**. 장르는 7개 고정 분류 체계로 자동 분류하되, 애매한 항목은 사용자 검토로 확정한다.

### 비목표 (M3)
- 원본 수정·이동·태그 재기록 (원본 NTFS는 **읽기 전용 — 복사만**).
- 오디오 재인코딩·포맷 변환·태그 정규화 기록(원본/복사본 모두 바이트 보존, `copy2`).
- `.enc`(Melon DRM) 복사·복호화.
- 완전 자동 무검토 분류(저신뢰는 사람 확인이 기본).

## 2. 컨텍스트 (실측)

- 소스: `/mnt/win/memory/음악` — 오디오 15,305개, **170GB**, ntfs3 읽기 전용.
- 대상: `/home`(`/dev/sda1` ext4) **여유 3.5T** → 전체 복사 가능.
- 장르 태그 신호(표본 250): `Classical`(51)·`Jazz`(24)·`Tango`·`Latin`·`World`·`Soundtrack`·`Opera`·`Bossa Nova`·`MPB` 등은 버킷에 거의 직결. 단 계층표기(`Classical/Piano`, `Jazz(Tango,World Fusion)`), **모지바케 한글**(`ºê¶óÁú¸®¾ð`=브라질리언), junk(`Other`/`Unknown`/`NON GENRE`/IRC 문자열) 혼재. **커스텀 구분(클래식기타·가요)은 태그에 없음** → 별도 감지 필요.

## 3. 아키텍처

M1 `core`(엔티티 모델·Store·resolver·`encoding.recover_text`·`wiki.safe_filename`)를 재사용하는 **새 패키지 `organize/`**. 4단계 파이프라인이 모두 SQLite(SSOT)를 경유한다. 산출물은 `/home`의 새 트리이며 원본은 불변.

```
src/music_wiki/organize/
  buckets.py    7버킷 taxonomy + 키워드 규칙표 + 한글/기타 감지
  classify.py   앨범 → (bucket, confidence, source). L1 규칙 / L2 외부 / L3 LLM
  review.py     저신뢰·애매 앨범 CSV export ↔ import(확정)
  plan.py       트랙 → 목적지 경로 계산, 충돌/중복/DRM/미상 처리
  apply.py      복사 실행(dry-run 기본), organized_path 기록
external/       MusicBrainzClient(기본) · DiscogsClient(선택) — 인터페이스 뒤
llm/            ClassifierLLM(Claude) — 인터페이스 뒤
```

### 데이터 흐름
M1 scan → 엔티티 DB → **classify**(genre_bucket 기록) → **review**(CSV 왕복) → **plan**(목적지 계산) → **apply**(복사). 위키는 추후 버킷·정리경로 표기 가능.

## 4. 7버킷 taxonomy + 폴더명

| 버킷 | 폴더명 |
|---|---|
| 클래식 | `클래식` |
| 가요(한국) | `가요` |
| 재즈 | `재즈` |
| 팝 | `팝` |
| 제3세계(탱고 포함) | `제3세계` |
| 클래식기타 | `클래식기타` |
| 경음악·OST | `경음악_OST` |
| 분류불가(폴백) | `미분류` |

폴더명은 파일시스템 안전(슬래시·콜론 제거)을 위해 `safe_filename` 적용. `경음악andOST`는 `경음악_OST`로 표기.

## 5. classify (3계층)

앨범 단위. 입력 = 정규화 아티스트/앨범/트랙명 + 복구된 장르 태그.

### L1 — 규칙 (1차, 대부분 커버)
`buckets.classify_by_rules(tags, artist, titles) -> (bucket|None, confidence, signals)`:
- 장르 태그를 `recover_text`로 복구 → 소문자화 → **키워드 규칙표** 매칭.
- **클래식기타**: 클래식 문맥 + 기타 신호(`classical guitar`/`기타`/`클래식기타`/알려진 기타리스트). 클래식보다 **우선 평가**.
- **가요**: 아티스트/앨범/제목에 **한글 음절 존재** + (가요/발라드/트로트/댄스/kpop) → 가요. (한글이어도 클래식/재즈면 해당 버킷 유지)
- 단일·명확 키워드 적중 = **고신뢰**; 복합태그·junk·한글/기타 판별필요 = **저신뢰**.

규칙표(요약):
- 클래식: classical, classic, 클래식, opera, 오페라, chamber, symphony, 교향, 협주, baroque, romantic, piano, sonata, 클래시카
- 클래식기타: classical guitar, 클래식기타, (guitar|기타)+클래식문맥
- 재즈: jazz, swing, bebop, hard bop, cool, fusion, 재즈 *(bossa·latin jazz는 저신뢰→검토)*
- 제3세계: world, 월드, tango, 탱고, latin, bossa, samba, mpb, folklore, flamenco, fado, brazil, brasil, ethnic, national folk, 제3세계
- 가요: 가요, 발라드, ballad(+한글), 트로트, trot, kpop, k-pop, 댄스, 인디(+한글)
- 팝: pop, rock, r&b, soul, funk, electronic, dance, hip hop, jpop, j-pop
- 경음악_OST: ost, o.s.t, soundtrack, screen music, score, 경음악, easy listening, instrumental, 연주, newage, new age

### L2 — 외부 DB (저신뢰·junk·빈칸만)
`MusicBrainzClient`(기본, 무료, ~1req/s 레이트리밋, 응답 캐시 디렉토리)로 아티스트+앨범 → genres/tags. 선택적 `DiscogsClient`(토큰 제공 시, style 정밀). 외부 장르를 다시 규칙표로 7버킷 매핑. **기본 off(`--enrich-genre`)**.

### L3 — LLM (그래도 애매)
`LocalLLMClient`(**로컬 LLM** — LM Studio OpenAI 호환 API, 기본 `http://localhost:1234/v1`, 기본 모델 Qwen3-14B): 아티스트·앨범·복구태그·트랙명 일부를 주고 7버킷 중 택1 + 신뢰도 + 근거. base_url·model은 config 노브(Qwen3/Gemma3 교체). **기본 off(`--classify-llm`)**. 상세: `2026-06-27-library-pages-and-local-llm-design.md`.

출력: `album.genre_bucket / genre_confidence(0~1) / genre_source(rule|musicbrainz|discogs|llm|manual)`. 미변경 앨범은 재실행 시 스킵(멱등).

## 6. review (신뢰도 게이트)

- `organize review-export --out review.csv --threshold 0.8`: confidence < threshold 또는 bucket=미분류인 앨범을 CSV로. 열 = `album_id, artist, album, proposed_bucket, confidence, source, signals`.
- 사용자가 `proposed_bucket` 열을 7버킷 중 하나로 수정.
- `organize review-import --in review.csv`: 수정된 버킷을 DB에 확정(`genre_source=manual, confidence=1.0`).
- 고신뢰 앨범은 검토 없이 통과.

## 7. plan (목적지 계산)

`plan.build_plan(store, target_root) -> list[CopyOp(src_abs, dst_abs)]`:
- 트랙별 목적지: `{target_root}/{safe(bucket)}/{safe(artist)}/{safe(album)}/{NN - safe(title)}.{ext}` (아티스트는 상위 폴더이므로 앨범 폴더에 아티스트명 중복하지 않음)
  - 디스크 다중이면 `NN` = `disc-track`(예 `1-03`), 단일이면 `track`. 트랙번호 없으면 원본 파일명 stem.
- **DRM 제외**: `source_file.is_drm=1` 건너뜀(별도 `DRM-목록.txt` 출력).
- **장르 미정**: `genre_bucket` 없으면 `미분류`.
- **충돌/중복**: 같은 목적지 경로 다수 → 같은 앨범 병합. 동일 목적지+동일 크기는 1개만(중복 제거). 서로 다른 내용이 같은 경로면 `…(2)` 접미.
- 멱등: 목적지가 이미 존재(+크기 동일)하면 op 생략.

## 8. apply (복사)

`apply.run(plan, *, dry_run=True) -> ApplyStats(planned, copied, skipped, drm_excluded, errors)`:
- **기본 dry-run** — 계획만 출력, 한 줄도 안 옮김. `--apply`로 실제 복사.
- `shutil.copy2`(NTFS→ext4, 메타데이터 보존). 부모 디렉토리 자동 생성.
- 멱등: 목적지 존재+크기 동일 → skip. 파일별 try/except로 한 파일 실패가 전체 복사를 중단시키지 않음(errors 카운트, 계속).
- 성공 시 `source_file.organized_path` 기록.

## 9. DB 확장 (M1 store)

- `album`: `genre_bucket TEXT`, `genre_confidence REAL`, `genre_source TEXT`.
- `source_file`: `organized_path TEXT`.
- 스키마는 `CREATE TABLE IF NOT EXISTS` + 누락 컬럼 `ALTER TABLE ADD COLUMN`(존재 시 무시)로 기존 DB에 비파괴 마이그레이션.

## 10. CLI (기존 music-wiki에 추가)

```
music-wiki classify        [--enrich-genre] [--classify-llm]   # 앨범 장르 버킷 산출 → DB
music-wiki review-export   [--out review.csv] [--threshold 0.8]
music-wiki review-import   [--in review.csv]
music-wiki organize        [--target ~/music-library] [--apply]  # plan(+복사). 기본 dry-run
```

## 11. 외부 의존

- MusicBrainz(기본, 무료, User-Agent 필수, ~1req/s, 디스크 캐시). Discogs(선택, 토큰). 둘 다 `--enrich-genre`에서만 호출, off 시 미접속.
- 로컬 LLM(선택, `--classify-llm`; LM Studio OpenAI 호환, 클라우드 비노출). 인터페이스 뒤로 감싸 단위테스트는 외부 호출 없음.

## 12. 엣지 · 안전 · 멱등

- 원본 불변(복사만), dry-run 기본 — 의도치 않은 대량 복사 방지.
- classify/plan/apply 모두 재실행 안전(멱등).
- 메타 없는 곡: M1 resolver의 폴더-폴백으로 아티스트/앨범 결정, 장르 없으면 `미분류`.
- 디스크 여유 점검: apply 시작 시 계획 총량 vs `target_root` 여유 비교, 부족하면 중단·안내.

## 13. 테스트

- `buckets`: 태그→버킷 케이스 테이블(Classical/Jazz/Tango/Soundtrack/junk/모지바케), 한글 감지(가요), 기타 감지(클래식기타) 분기.
- `classify`: L1 규칙 우선순위(클래식기타>클래식), 저신뢰 표시; L2/L3는 fake 클라이언트.
- `review`: CSV export→수정→import 왕복이 DB에 확정.
- `plan`: 경로 규칙, 디스크번호, DRM 제외, 미분류 폴백, 충돌·중복 병합.
- `apply`: 임시 디렉토리 픽스처로 복사 + 멱등(재실행 skip) + 파일오류 격리. 실제 라이브러리 비의존.

## 14. 구현 단계 (별도 plan)

- **M3-A (핵심·선)**: DB 컬럼 마이그레이션 → `buckets` 규칙표 → `classify` L1(규칙) → `review` CSV → `plan` → `apply`(dry-run+복사) → CLI. **태그+규칙만으로 분류·정리되는 완결 슬라이스.**
- **M3-B (보강·후)**: L2 외부(MusicBrainz/Discogs) + L3 LLM 계층으로 junk/애매 앨범 정확도 향상.

각 단계는 별도 writing-plans → 구현 사이클.
