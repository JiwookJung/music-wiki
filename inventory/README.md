# LP/CD 실물 인벤토리

집 보관장 사진 16장 → 비전 인식 → 사용자 검수 → DB 보강(Discogs/MusicBrainz) →
분류코드(도서관식 청구기호) 부여까지의 산출물.

- `20260726_LPCD_목록_v2.xlsx` — **최종본** (21시트: 위치별 16 + 분류코드표/중복목록/미식별목록/정리계획/라벨인쇄)
- `LPCD_목록.xlsx` → `20260717…` → `20260726…` — 이전 버전 체인(자동인식 → 사용자 편집)
- `data/` — 사진별 인식 JSON(v1), 최종 통합 데이터(`lpcd_v3.json`), API 캐시
- `scripts/` — 보강(enrich_mb/discogs_enrich/discogs_loose/enrich_v2)·조립(build_v3_xlsx) 스크립트
  - 재생성: `data/lpcd_v3.json` 경로를 맞춘 뒤 `python scripts/build_v3_xlsx.py`

분류코드 체계: **매체접두(LP-/CD-)** + 장르문자(C/CG/G/J/T/W/P/K/KN/O/X) + 아티스트초성·번호(간격3~4) + 앨범번호.
예) `LP-J-B01-02`(재즈 Bill Evans 2번째), `CD-C-B0-G01-01`(클래식 Bach·Gould).
라벨 시트 3종: `라벨인쇄-LP`(724) · `라벨인쇄-CD`(200) · `라벨인쇄-전체`(924, LP→CD 순).
같은 앨범을 LP·CD 둘 다 소장하면 **실물마다** 접두가 달라진다(예: `LP-J-M29-01` / `CD-J-M29-01`).
클래식은 `C-작곡가성1자리-연주자성2자리-앨범2자리`(예: C-B0-G01-01 = Bach·Gould·Goldberg).
CG = DG 옐로우 게이트폴드 2864 시리즈(좌측선반3층 전용), KN = 한국 비매품.

## 파이프라인 (앨범 추가/수정 시)

1. 엑셀 위치 시트에 행 추가(매체·장르·아티스트·앨범 필수, 클래식은 작곡가·연주자)
2. `python scripts/pipeline.py` 실행 → 분류코드 자동 부여 + 전 시트(라벨인쇄 포함) 재생성
   - **기존 코드는 불변**(`data/code_registry.json`에 고정): 새 아티스트는 이웃 사이
     빈 번호로 삽입, 새 앨범은 다음 번호. 신규 코드는 실행 결과에 출력(라벨 추가 인쇄용)
   - `--dry-run` 으로 미리보기 가능

## 디지털(mp3) ↔ 실물 연동

`python scripts/link_digital.py --wiki`
- 디지털 라이브러리(~/music-wiki-vault/music-wiki.db)와 아티스트+앨범 정규화 매칭
- 엑셀 `디지털` 열 ✓ / 위키 앨범 페이지에 `실물 음반: LP J-B01-02` + 🟤 바이닐 배지

## 웹UI 발급분 반영 (ser8 → 백엔드)

ser8 `/add` 에서 발급하면 `data/pending_albums.json` 에 쌓인다. 백엔드에서:

```bash
python inventory/scripts/apply_pending.py --dry-run   # 무엇이 들어갈지 확인
music-wiki update                                     # 엑셀 반영 + 코드 재생성 + md/그래프까지
```

- 멱등: 이미 엑셀에 있는 앨범은 건너뛰고 큐에서 제거, 실패분만 남아 재시도.
- 엑셀 저장 전 `.bak` 백업, 반영 이력은 `data/applied_albums.json` 에 축적.

## 시트 구성

| 시트 | 생성 주체 | 내용 |
|---|---|---|
| 위치별 16개 (CD윗층 … LP침대옆) | 사용자 편집 + pipeline | 실물 목록(정본) |
| 분류코드표 · 중복목록 · 미식별목록 · 정리계획 | pipeline 자동 | 재실행마다 재생성 |
| 라벨인쇄-LP / -CD / -전체 | pipeline 자동 | 라벨 프로그램용(열당 136행) |
| **정리작업** | 수동 생성 | 물리 정리 체크리스트(중복 빼기·제자리로) |
| **라벨재발급N** | 수동 생성 | 코드가 바뀐 LP만 모아 재출력용. 변경 라운드마다 번호 증가 |

`pipeline.py` 는 워크북을 새로 만들지만 **자동 생성 대상이 아닌 시트는 그대로 옮겨온다**
(정리작업·라벨재발급N 등이 사라지지 않음).
