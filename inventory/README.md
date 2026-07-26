# LP/CD 실물 인벤토리

집 보관장 사진 16장 → 비전 인식 → 사용자 검수 → DB 보강(Discogs/MusicBrainz) →
분류코드(도서관식 청구기호) 부여까지의 산출물.

- `20260726_LPCD_목록_v2.xlsx` — **최종본** (21시트: 위치별 16 + 분류코드표/중복목록/미식별목록/정리계획/라벨인쇄)
- `LPCD_목록.xlsx` → `20260717…` → `20260726…` — 이전 버전 체인(자동인식 → 사용자 편집)
- `data/` — 사진별 인식 JSON(v1), 최종 통합 데이터(`lpcd_v3.json`), API 캐시
- `scripts/` — 보강(enrich_mb/discogs_enrich/discogs_loose/enrich_v2)·조립(build_v3_xlsx) 스크립트
  - 재생성: `data/lpcd_v3.json` 경로를 맞춘 뒤 `python scripts/build_v3_xlsx.py`

분류코드 체계: 장르문자(C/CG/G/J/T/W/P/K/KN/O/X)-아티스트초성+번호(간격3~4)-앨범번호.
클래식은 `C-작곡가성1자리-연주자성2자리-앨범2자리`(예: C-B0-G01-01 = Bach·Gould·Goldberg).
CG = DG 옐로우 게이트폴드 2864 시리즈(좌측선반3층 전용), KN = 한국 비매품.
