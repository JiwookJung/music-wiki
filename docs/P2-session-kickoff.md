# P2 music-wiki — 세션 킥오프 컨텍스트

이 문서는 **별도 세션에서 P2를 병렬로 시작**하기 위한 인수인계 노트다. (P1 family-photos는 다른 세션에서 동시에 진행 중)

## 목표
저장된 mp3 등 음악을 정리하고 **LLM 기반 마크다운 위키**(아티스트/앨범/트랙)로 만드는 서비스. 외부 비노출, 로컬용.

## 데이터 소스 (읽기 전용)
- `/mnt/win/memory/음악` — 약 **15,300 트랙**(mp3 위주, flac 일부), ~169GB. Windows NTFS, 우분투에 **읽기 전용 자동 마운트**(`/etc/fstab`, ntfs3). 원본은 절대 수정하지 않는다.
- 산출물(위키 md, DB, 캐시)은 전부 ext4 `/home`에 생성. 기존 `~/Obsidian Vault`와 연계 가능.

## 선결정 사항
- 저장: **마크다운 위키 `[[링크]]` + SQLite(또는 프론트매터)**로 시작. **neo4j는 v1 보류** — 관계 질의가 실제로 필요해지면 그때 도입.
- P3(lp-collection)와 **음악 지식 그래프(아티스트·앨범·레이블·장르·연도)를 공유**할 예정 → 데이터 모델을 P3와 연결 가능하게 설계.
- 메타데이터: ID3 태그(아티스트/앨범/트랙/연도/장르) 우선, 부족하면 MusicBrainz 등 외부 보강 + LLM 요약/해설 생성.

## 시작 절차 (이 세션에서)
1. brainstorming 스킬로 P2 설계를 진행한다(요구사항·범위 확정 → 설계 → 승인 → 스펙 작성).
2. 먼저 `/mnt/win/memory/음악` 현황 스캔(확장자·개수·용량, ID3 태그 채움 비율 샘플)으로 데이터 형태 파악.
3. 설계 확정 후 스펙을 `docs/superpowers/specs/YYYY-MM-DD-music-wiki-design.md`에 작성·커밋.

## 참고 (전체 계획)
- 워크스페이스: `/home/neotango/media-archive/` (family-photos / music-wiki / lp-collection, 각자 독립 repo, 각자 GitHub + CI).
- 관련 메모리: `media-projects-plan`, `windows-ntfs-mounts`, `media-archive-workspace` (MEMORY.md에서 자동 로드됨).
- 진행 순서는 원래 P1→P2→P3였으나, 사용자 요청으로 **P2를 별도 세션 병렬 진행**.

## 병렬 작업 주의
- 이 세션은 **반드시 `music-wiki` 디렉토리에서만** 작업(P1 세션과 파일/깃 충돌 방지).
- 공유 자원인 NTFS 마운트는 읽기 전용 → 동시 읽기 안전.
- 메모리 파일은 가급적 P2 전용 항목만 추가(같은 파일 동시 편집 지양).
