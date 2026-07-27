# music-wiki 확장 — ser8 프론트 + Ubuntu 백엔드 2계층 설계

- 상태: 초안 (feasibility 검토 단계)
- 작성일: 2026-07-27
- 기반: M1~M3 + Phase1/2 + OKF md 저장소 + `music-wiki update` 파이프라인 + LP/CD 분류코드 레지스트리 (모두 완료 자산)

## 1. 목표 / 비목표

### 목표
1. **ser8 미니PC(16GB/320GB, Ubuntu Linux, 24시간)** 를 상시 프론트로: md 지식 뷰어 + 음악/YouTube 플레이어 + 앨범 추가 UI + **구매 즉시 분류번호 발급** + LLM 질의.
2. **Ubuntu PC(현행)** 는 온디맨드 백엔드로: mp3 원본(170GB)·마스터 저장소·무거운 배치(스캔/재인식/대량 해설)·에이전트(hermes, OpenClaw, Claude Code).
3. 데이터는 **음반(실물) ∪ mp3(디지털) 합집합**의 단일 카탈로그로 통합, md(OKF)로 지식화. 필요 시 Neo4j 그래프(장르-아티스트-앨범-곡) + 임베딩 검색.
4. LLM은 **Claude 정기구독**을 활용 — ser8에 Claude Code 설치, `claude -p`(헤드리스)로 앱이 래핑. 추가 API 과금 없음.

### 비목표
- mp3의 ser8 이전(사용자 결정: Ubuntu 유지). → 로컬 재생은 Ubuntu 가동 시에만, 상시 재생은 YouTube가 담당.
- 외부 **공개** 서비스(불특정 다수 접근). 단, **본인 외부 접속은 Tailscale로 지원**(compose profile `remote`) — 포트 개방·도메인 불필요.
- 원본 음악 파일 수정(기존 원칙 유지).

## 2. 시스템 구성

```
[ser8 · 24h ON]                          [Ubuntu PC · 필요시 ON]
┌─────────────────────────────┐          ┌──────────────────────────────┐
│ FastAPI 웹앱 (Docker)        │   LAN    │ mp3 원본 170GB (읽기전용)      │
│  · md 뷰어(OKF 렌더)         │◄────────►│ music-wiki 마스터 repo        │
│  · 플레이어(YouTube 상시     │  git &   │  (SQLite·md·inventory·registry)│
│    / 로컬mp3=Ubuntu 온라인시)│  NFS/HTTP│ 배치: update·재인식·대량해설    │
│  · 앨범 추가 + 분류번호 발급  │          │ 에이전트: hermes/OpenClaw/     │
│  · LLM 패널(claude -p 래핑)  │          │          Claude Code           │
│ 데이터 사본: md·SQLite·      │   WoL    │                              │
│  registry·youtube_links      │─────────►│ (ser8이 매직패킷으로 깨움)      │
│ (선택) Neo4j + 임베딩 인덱스  │          │                              │
└─────────────────────────────┘          └──────────────────────────────┘
        └── git push/pull (GitHub JiwookJung/music-wiki = 동기화 허브)
```

**역할 원칙**: ser8 = 읽기·발급·가벼운 LLM(상시). Ubuntu = 원본·배치·무거운 작업(온디맨드). 동기화 매체 = **기존 GitHub repo**(md·registry·inventory 데이터가 이미 커밋 대상) + mp3만 네트워크 마운트.

## 3. 데이터 계층 — 합집합 카탈로그

### 3.1 단일 카탈로그(이미 대부분 존재)
- **디지털**: `music-wiki.db` (1,185앨범/15,266곡) — 스캔·분류·해설·physical_code·YouTube링크.
- **실물**: `inventory/data/*.json` + 분류코드 레지스트리 (924매/816코드).
- **합집합 뷰**: `link_digital.py` 매칭을 확장해 **catalog 통합 테이블**(album 단위: 식별키, 디지털유무, 실물코드/위치, 해설, 대표곡, YouTube) 생성 → 프론트 API의 단일 소스. SQLite에 `catalog` 뷰/테이블 추가로 구현(신규 DB 불필요).

### 3.2 md 저장소
- 현행 `~/music-wiki-vault`(OKF md 3,043개)를 **git repo화**하여 GitHub 경유로 ser8과 동기(콘텐츠가 재생성 가능한 파생물이므로 충돌 시 마스터 재생성으로 해소). Obsidian은 양쪽 어디서든 열람 가능.

### 3.3 Neo4j + 임베딩 (선택 계층)
- 그래프: `(장르)-[:HAS]->(아티스트)-[:MADE]->(앨범)-[:CONTAINS]->(곡)` + `(앨범)-[:PHYSICAL {code}]`, `(앨범)-[:SIMILAR]`(임베딩 kNN에서 유도).
- 임베딩: 해설+메타 텍스트를 다국어 모델(예: `BAAI/bge-m3` 또는 `paraphrase-multilingual-MiniLM`)로 벡터화 → **Neo4j 5 vector index** 또는 경량 대안 **sqlite-vec/FAISS**.
- **채택(2026-07-27, 사용자 결정)**: 다른 프로젝트와 구성을 통일하기 위해 **Neo4j를 기본 채택**. E0에서 이미 적재·검증 완료(Album 1,950 / Artist 1,048 / Genre 13 / Track 5,875 / Location 16). 임베딩(유사검색)은 E3에서 Neo4j vector index 로 추가.

## 4. ser8 웹앱 (프론트) 설계

FastAPI + 정적 SPA(경량 Vanilla/HTMX 우선, 필요시 React) 단일 Docker 이미지 — 기존 M4 방향 그대로.

| 모듈 | 내용 |
|---|---|
| **뷰어** | vault md를 OKF frontmatter 파싱해 렌더(홈/장르/아티스트/앨범). `[[위키링크]]`→내부 라우팅. 검색(제목/아티스트/해설 전문 + 추후 임베딩 유사검색) |
| **플레이어** | ① YouTube: `youtube_links.json`의 영상 iframe 임베드(24h 가능) ② 로컬 mp3: Ubuntu 온라인 시 스트리밍(백엔드 파일서버). 오프라인이면 자동으로 YouTube 폴백 + "원본 재생하려면 백엔드 깨우기" 버튼(WoL) |
| **추가 UI** | (a) **음반 구매 등록**: 아티스트·앨범·장르(·작곡가/연주자) 입력 → **분류번호 즉시 발급**(§5) → 위치 선택 → 인벤토리 반영 + md 생성 (b) **mp3 추가 알림**: 파일은 Ubuntu에 넣고, ser8 UI에서 "동기화 요청" 큐 등록 → Ubuntu 부팅 시 `update` 자동 실행 |
| **LLM 패널** | `claude -p` 헤드리스 래핑: 새 앨범 해설 생성, 자연어 질의("피아졸라 실물 어디 있어?" → catalog 조회 + 답), md 요약. 큐+타임아웃 관리, 동시 1~2 세션 제한 |
| **관리** | Ubuntu WoL 버튼, 동기화 상태(마지막 git pull, mp3 마운트 여부), 백엔드 작업 큐 조회 |

## 5. 분류번호 발급 서비스 (구매 시 즉시)

- 현행 `pipeline.py`의 레지스트리 로직(간격 삽입·기존 번호 불변)을 **`codelib` 모듈로 분리**해 ser8 API가 직접 호출: `POST /api/albums` → 코드 계산·`code_registry.json` 갱신·커밋 → **화면에 코드 표시**(라벨에 수기/즉석 인쇄).
- **발급 주체 단일화(중요)**: 레지스트리 쓰기는 **ser8만** 수행(24h 가용·경합 방지). Ubuntu `pipeline.py`는 pull 후 읽기 전용으로 코드 재현(신규 발급 없음 모드). 이렇게 하면 두 기계가 같은 번호를 다르게 발급하는 충돌이 원천 차단됨.
- 발급 이력은 registry 커밋 로그(git)가 감사 추적 역할.

## 6. 백엔드(Ubuntu) 역할

- **저장소 마스터**: mp3 원본(불변) + repo(중앙은 GitHub). NFS(또는 SMB/HTTP range) 로 mp3 export → ser8이 마운트/스트리밍.
- **배치**: 부팅 시(또는 수동) `music-wiki update` — ser8이 쌓아둔 요청 큐(새 mp3 스캔, 대량 해설 등) 소화 → git push → ser8 pull.
- **에이전트**: hermes agent / OpenClaw / Claude Code — 사용자의 기존 도구를 그대로 이 repo 위에서 구동(대화형·자동화 작업). 본 설계는 이들이 접근할 **일관된 데이터 계약**(SQLite·OKF md·JSON)을 제공하는 데 집중.
- **대량 LLM 작업**: 552건 해설처럼 큰 배치는 Ubuntu에서 Claude Code(구독)로 — 지금까지의 세션 방식 그대로.

## 7. Feasibility 평가

| 항목 | 판단 | 근거/수치 |
|---|---|---|
| ser8 저장 320GB | **여유 큼(실측)** | mp3 제외 시 vault 92MB·DB 5.1MB·yt링크 0.2MB·DB 12MB·youtube캐시 <1MB·임베딩(2.2만×1024f32≈90MB)·Neo4j <2GB·OS/Docker ~30GB → 총 <40GB |
| ser8 메모리 16GB | **충분** | FastAPI+SPA <0.5GB, Neo4j heap 2GB, 임베딩 모델(CPU) 1~2GB, Claude Code 세션 ~1GB → 피크 ~6GB |
| 24h 재생(로컬 mp3 없이) | **YouTube로 해결** | 정확 링크 1,950건 수집 중(현재 진행). 미해결 앨범은 검색 링크 폴백 |
| 로컬 mp3 스트리밍 | **가능(조건부)** | Ubuntu 가동 시 NFS/HTTP. WoL로 ser8에서 원격 기동(BIOS 설정 필요 — 확인 항목) |
| Claude 구독 헤드리스 | **확인됨(실측 2026-07-27)** | `claude -p` 구독 계정 비대화 호출·응답 성공. 주의: 프로젝트 폴더 밖 전용 작업디렉토리에서 최소 권한으로 래핑할 것(레포 컨텍스트 오염 방지). ser8 로그인 1회 필요 |
| Neo4j Community | **가능** | ARM/x86 Docker 이미지, 데이터 규모 미미. 단 vector index는 Neo4j 5.13+ 확인 필요 → 대안 sqlite-vec/FAISS 준비 |
| 임베딩 생성(CPU) | **가능(라이브러리 설치 필요)** | sentence-transformers/faiss 미설치 — pip 1회 설치. 2.2만 문서×짧은 텍스트, MiniLM급 CPU 처리 수분~수십분(1회성) |
| md/registry 동기화 | **git으로 단순** | 이미 GitHub에 inventory·registry 커밋 중. vault만 repo화 추가 |
| 위험(중) | ser8 WoL/절전 설정, YouTube embed 제한(일부 영상 embed 금지 → 새탭 폴백), 구독 사용량 정책 변화 | 완화책 각 명시 |

**결론: 전 항목 실현 가능.** 유일한 구조적 제약은 사용자가 수용한 "Ubuntu 꺼짐 시 로컬 mp3 재생 불가"이며 YouTube+WoL로 완화.

## 8. 단계별 로드맵 (각 단계 = 독립 spec→plan→구현 사이클)

- **E0 (완료, 2026-07-27)**: `claude -p` 헤드리스 실증, vault git화(3,046파일), **catalog 통합 테이블 1,950건**, 웹앱 프로토(뷰어·검색·YouTube 임베드·정리장/그래프 탐색), **Docker 스택**(`deploy/docker-compose.yml`: web+neo4j+tailscale), **Neo4j 적재**, **마이그레이션 가이드**(`deploy/MIGRATION.md`). 전부 컨테이너로 기동 검증.
- **E1 (ser8 가동)**: ser8 Ubuntu 설치→Docker→웹앱 배포→vault/DB pull→YouTube 플레이어 상시화. WoL 확인.
- **E2 (완료, 2026-07-27)**: `/add` 웹UI + `POST /api/issue` 분류번호 발급(레지스트리 재사용, 빈 번호 삽입 검증: 신규 아티스트 J-E06 삽입 시 기존 코드 불변), `pending_albums.json` 대기목록, `/ask` LLM 패널(`claude -p`). 테스트 2건 추가(131 통과).
- **E1-a (완료, 2026-07-27)**: 로컬 mp3 스트리밍 UI — 앨범 페이지 수록곡 목록·클릭 재생·연속재생, Range(206) 지원, 원본 오프라인 시 자동 '(오프라인)' 표기 + YouTube 폴백, `/api/status`.
- **E3 (완료, 2026-07-27)**: Neo4j vector index(384d, multilingual-MiniLM) + 앨범 유사검색 UI. CPU 33초로 1,950건 임베딩 — ser8에서도 동일.

## 9. 리스크 & 완화
- **레지스트리 이중 발급** → §5 단일 발급자(ser8) 규칙으로 차단.
- **vault 충돌** → md는 파생물: 충돌 시 마스터 데이터로 재생성이 정답(문서화).
- **YouTube 링크 부패/오매칭** → 링크는 캐시일 뿐, md 재생성으로 교체 용이. 플레이어에 "다른 영상 찾기(검색)" 버튼.
- **ser8 성능 부족 시** → Neo4j·임베딩을 Ubuntu로 이전(설계상 계층 분리돼 있어 이동 쉬움).
