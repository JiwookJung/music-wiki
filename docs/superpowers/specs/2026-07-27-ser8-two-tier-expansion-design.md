# music-wiki 확장 — ser8 단독 운영 설계 (구 2계층)

- 상태: **구조 변경 확정 (2026-07-28)** — 2계층 → **ser8 단독 운영**
- 작성일: 2026-07-27 (2계층 초안) / 개정: 2026-07-28
- 기반: M1~M3 + Phase1/2 + OKF md 저장소 + `music-wiki update` 파이프라인 + LP/CD 분류코드 레지스트리 (모두 완료 자산)

> **구조 변경 요약(2026-07-28, 사용자 결정)**
> mp3 170GB를 **1TB 외장 SSD**에 담아 ser8에 USB로 직결하기로 하면서, 이 문서의
> 전제였던 "mp3는 Ubuntu에 유지" 제약이 사라졌다. 그 결과:
> - **ser8이 전부 담당** — 웹·그래프·재생·발급·배치·에이전트.
> - **NFS·WoL 불필요** — 상시 네트워크 의존이 사라져 두 기계 간 결합이 0이 됨.
> - 현 Ubuntu PC는 **NTFS 원본 백업 보관소**로만 남고 평소 꺼둔다(GPU 작업 시에만 기동).
>
> 아래 본문의 2계층 서술은 **역사적 기록**이며, NFS·WoL 절차는 SSD를 쓰지 않을 때의
> 폴백으로만 유효하다. 실제 작업은 [SER8-TASKS.md](../../../deploy/SER8-TASKS.md) 를 따른다.

## 1. 목표 / 비목표

### 목표
1. **ser8 미니PC(16GB, Ubuntu Linux, 24시간)** 를 단독 운영 서버로: md 지식 뷰어 + 음악/YouTube 플레이어 + 앨범 추가 UI + **구매 즉시 분류번호 발급** + LLM 질의 + 배치.
2. **mp3 원본 170GB는 외장 SSD(LABEL=`MUSIC`, ext4)** 로 ser8에 직결 — `/mnt/music`, 음악은 `media/` 하위. ~~Ubuntu PC를 온디맨드 백엔드로 사용~~ (2026-07-28 폐기).
3. 데이터는 **음반(실물) ∪ mp3(디지털) 합집합**의 단일 카탈로그로 통합, md(OKF)로 지식화. 필요 시 Neo4j 그래프(장르-아티스트-앨범-곡) + 임베딩 검색.
4. LLM은 **Claude 정기구독**을 활용 — ser8에 Claude Code 설치, `claude -p`(헤드리스)로 앱이 래핑. 추가 API 과금 없음. (ser8은 GPU가 없어 로컬 LLM은 비현실적)

### 비목표
- ~~mp3의 ser8 이전~~ → **2026-07-28 뒤집힘**: 외장 SSD 직결로 이전 확정. 로컬 재생이 24시간 가능해졌고 YouTube는 보조 수단으로 격하.
- 외부 **공개** 서비스(불특정 다수 접근). 단, **본인 외부 접속은 Tailscale로 지원**(compose profile `remote`) — 포트 개방·도메인 불필요.
- 원본 음악 파일 수정(기존 원칙 유지). Ubuntu PC의 NTFS 원본은 **백업본으로 보존**한다.

## 2. 시스템 구성 (2026-07-28 개정)

```
[ser8 · 24h ON — 전부 여기서]                    [Ubuntu PC · 평소 OFF]
┌────────────────────────────────────┐          ┌──────────────────────────┐
│ FastAPI 웹앱 + Neo4j (Docker)       │          │ NTFS 5.8TB               │
│  · md 뷰어(OKF 렌더)                │          │  = mp3 원본 백업 사본     │
│  · 플레이어(로컬 mp3 상시 + YouTube) │          │    (지우지 말 것)         │
│  · 앨범 추가 + 분류번호 발급         │          │ GPU 2장 — 로컬 LLM 등     │
│  · LLM 패널(claude -p 래핑)         │          │   필요할 때만 기동         │
│  · 배치(update·재인식·대량해설)      │          └──────────────────────────┘
│  · 에이전트(hermes/OpenClaw/Claude) │
│ 데이터: vault(md·SQLite)·inventory  │            ※ 상시 네트워크 의존 없음
│         ·registry·임베딩             │              (NFS·WoL 불필요)
├────────────────────────────────────┤
│ 외장 SSD 1TB (LABEL=MUSIC, ext4)    │ ← USB 직결
│   /mnt/music/media = mp3 170GB      │
└────────────────────────────────────┘
        └── git push/pull (GitHub JiwookJung/music-wiki = 백업 겸 이력)
```

**역할 원칙**: ser8 = **모든 쓰기와 읽기**(발급·스캔·갱신·재생·LLM). Ubuntu PC = 원본 백업 보관소 + GPU 작업용 예비. 백업 매체 = **GitHub repo**(코드·inventory·registry) + Ubuntu의 NTFS 원본(mp3).

> 구 2계층에서의 "레지스트리 단일 발급자" 규칙(§5)은 그대로 유효하다. 발급 주체가
> ser8 하나뿐이므로 이제는 구조적으로 이중 발급이 불가능하다.

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
| **플레이어** | ① 로컬 mp3: 외장 SSD에서 **24시간 상시** 스트리밍(Range 206 지원, 연속재생) ② YouTube: `youtube_links.json` iframe 임베드 — 이제 **보조 수단**(SSD 미장착·음원 없는 앨범용). SSD를 빼면 자동으로 '(오프라인)' 표기 + YouTube 폴백 |
| **추가 UI** | (a) **음반 구매 등록**: 아티스트·앨범·장르(·작곡가/연주자) 입력 → **분류번호 즉시 발급**(§5) → 위치 선택 → 인벤토리 반영 + md 생성 (b) **mp3 추가**: `/mnt/music/media/` 에 파일을 넣고 ser8에서 `music-wiki update` 실행(2026-07-28: 큐·원격 동기화 불필요해짐) |
| **LLM 패널** | `claude -p` 헤드리스 래핑: 새 앨범 해설 생성, 자연어 질의("피아졸라 실물 어디 있어?" → catalog 조회 + 답), md 요약. 큐+타임아웃 관리, 동시 1~2 세션 제한 |
| **관리** | 동기화 상태(SSD 마운트 여부·트랙 수 `/api/status`), 배치 실행 상태. ~~WoL 버튼~~(2026-07-28 불필요) |

## 5. 분류번호 발급 서비스 (구매 시 즉시)

- 현행 `pipeline.py`의 레지스트리 로직(간격 삽입·기존 번호 불변)을 **`codelib` 모듈로 분리**해 ser8 API가 직접 호출: `POST /api/albums` → 코드 계산·`code_registry.json` 갱신·커밋 → **화면에 코드 표시**(라벨에 수기/즉석 인쇄).
- **발급 주체 단일화(중요)**: 레지스트리 쓰기는 **ser8만** 수행. 2026-07-28 단독 운영 확정으로 발급 주체가 물리적으로 하나뿐이 되어, 이중 발급은 이제 **구조적으로 불가능**하다(규칙 → 사실).
- 발급 이력은 registry 커밋 로그(git)가 감사 추적 역할.

## 6. 역할 분담 (2026-07-28 개정)

### ser8 (전담)
- **저장소**: 외장 SSD의 mp3 원본 + vault(md·SQLite) + inventory/registry. 중앙 백업은 GitHub.
- **배치**: `music-wiki update` — 스캔·재인식·대량 해설·`apply_pending.py` 까지 ser8에서 직접 실행. 원격 큐·pull 왕복이 사라짐.
- **에이전트**: hermes agent / OpenClaw / Claude Code 를 ser8의 repo 위에서 구동. 본 설계는 이들이 접근할 **일관된 데이터 계약**(SQLite·OKF md·JSON)을 제공하는 데 집중.
- **LLM**: ser8은 GPU가 없으므로 Claude Code 구독 헤드리스(`claude -p`)가 기본 경로. 552건 해설 같은 대량 배치도 동일 방식.

### Ubuntu PC (예비)
- **원본 백업 보관소**: NTFS 5.8TB의 mp3 원본 170GB — SSD 사본이 깨졌을 때의 복구원. **지우지 않는다.**
- **GPU 작업**: 로컬 LLM(LM Studio 등)이 필요할 때만 기동. ser8에서 `LLM_BASE_URL`로 호출 가능.
- 평소에는 꺼둬도 ser8 서비스에 아무 영향이 없다.

## 7. Feasibility 평가

아래는 **ser8 위에서 직접 측정한 값**(2026-07-28)으로 갱신한 표. 초안의 "320GB/16GB" 가정과 실제가 달랐다.

| 항목 | 판단 | 근거/수치 (2026-07-28 ser8 실측) |
|---|---|---|
| ser8 저장 | **스택은 여유, mp3는 SSD 필수** | NVMe 476.9GB가 이미 분할됨: 루트 ext4 254.7GB(**여유 167GB**) + Windows NTFS 221.5GB(듀얼부트). **mp3 170GB는 루트에 안 들어감** → 외장 SSD 직결이 이 구조의 전제. 스택 자체는 vault 97MB·Neo4j·임베딩 포함 40GB 미만 |
| ser8 메모리 | **가능하나 여유는 예상보다 적음** | 총 11GiB(초안의 16GB는 iGPU 예약 등으로 실사용 11GiB). 기존 coinbot 스택이 5.9GiB 상주 → **가용 5.5GiB**. Neo4j heap 1G+pagecache 512M로 기동해 문제 없으나, 압박 시 `NEO4J_HEAP=512M`로 축소 |
| 24h 재생 | **로컬 mp3로 상시 가능** | 외장 SSD 직결이므로 Ubuntu 가동 여부와 무관. YouTube는 음원 없는 앨범용 보조로 격하 |
| 로컬 mp3 스트리밍 | **가능(무조건)** | ~~NFS/WoL 조건부~~ → SSD 직결. 유의점은 USB 절전(`usbcore.autosuspend=-1`)과 fstab `nofail` |
| Claude 구독 헤드리스 | **확인됨(ser8 실측 2026-07-28)** | ser8에 CLI 기설치(2.1.220)·로그인 완료, `claude -p` 응답 성공. 주의: 프로젝트 폴더 밖 전용 작업디렉토리에서 최소 권한으로 래핑([acquire.py](../../../webapp/acquire.py) 가 임시 디렉토리 사용) |
| Neo4j Community | **확인됨(ser8 실측)** | `neo4j:5.26-community` 컨테이너 기동·healthy. vector index 요건(5.13+) 충족 |
| 임베딩 생성(CPU) | **가능** | 이미지에 sentence-transformers 포함(빌드됨). 1,950건 CPU 33초(개발 PC 실측) |
| md/registry 동기화 | **불필요해짐** | 단독 운영이라 기계 간 동기화 자체가 없음. GitHub은 백업·이력 용도 |
| 네트워크 | **주의** | ser8은 현재 **Wi-Fi**(`wlp2s0`) 연결. 단독 운영에서는 재생 경로가 로컬이라 영향 없으나, 체크리스트 권장은 유선 |
| 위험(중) | USB 절전으로 인한 재생 끊김, SSD 단일 사본 의존, YouTube embed 제한, 구독 사용량 정책 변화 | 완화책 §9 |

**결론: 전 항목 실현 가능.** 2026-07-27 초안의 유일한 구조적 제약("Ubuntu 꺼짐 시 로컬 mp3 재생 불가")은 외장 SSD 직결로 **제거됨**.

## 8. 단계별 로드맵 (각 단계 = 독립 spec→plan→구현 사이클)

- **E0 (완료, 2026-07-27)**: `claude -p` 헤드리스 실증, vault git화(3,046파일), **catalog 통합 테이블 1,950건**, 웹앱 프로토(뷰어·검색·YouTube 임베드·정리장/그래프 탐색), **Docker 스택**(`deploy/docker-compose.yml`: web+neo4j+tailscale), **Neo4j 적재**, **마이그레이션 가이드**(`deploy/MIGRATION.md`). 전부 컨테이너로 기동 검증.
- **E1 (ser8 가동, 진행 중 2026-07-28)**: ser8 Ubuntu→Docker→웹앱 배포→vault/DB 이관→외장 SSD 직결. 완료분: 절전 마스킹, Docker autostart, `deploy-web` 이미지 빌드, **Neo4j healthy**, `.env` 작성, `claude -p` 검증. 잔여: **vault 100MB 이관**과 **외장 SSD 장착**(둘 다 물리 작업) → 적재 3종 → A7 검증. ~~WoL 확인~~(단독 운영으로 불필요).
- **E2 (완료, 2026-07-27)**: `/add` 웹UI + `POST /api/issue` 분류번호 발급(레지스트리 재사용, 빈 번호 삽입 검증: 신규 아티스트 J-E06 삽입 시 기존 코드 불변), `pending_albums.json` 대기목록, `/ask` LLM 패널(`claude -p`). 테스트 2건 추가(131 통과).
- **E1-a (완료, 2026-07-27)**: 로컬 mp3 스트리밍 UI — 앨범 페이지 수록곡 목록·클릭 재생·연속재생, Range(206) 지원, 원본 오프라인 시 자동 '(오프라인)' 표기 + YouTube 폴백, `/api/status`.
- **E2-a (완료, 2026-07-27)**: `apply_pending.py` — ser8 발급 큐를 백엔드 엑셀에 자동 반영(멱등·백업·이력), `music-wiki update` 1단계로 편입. E2E 검증(J-E06-01 발급→42행 추가→롤백).
- **E3 (완료, 2026-07-27)**: Neo4j vector index(384d, multilingual-MiniLM) + 앨범 유사검색 UI. CPU 33초로 1,950건 임베딩 — ser8에서도 동일.

## 9. 리스크 & 완화 (2026-07-28 개정)
- **레지스트리 이중 발급** → 해소됨. 단독 운영으로 발급 주체가 하나뿐(§5).
- **vault 충돌** → 해소됨. 기계 간 동기화가 없어 충돌 지점이 사라짐. (md는 여전히 파생물이므로 손상 시 마스터 데이터로 재생성이 정답)
- **SSD 단일 장애점(신규·중요)** → mp3가 외장 SSD 한 벌에만 있으면 SSD 고장 = 데이터 소실. **Ubuntu PC의 NTFS 원본을 백업본으로 반드시 보존**하고, ser8에서 추가한 mp3는 주기적으로 그쪽에 반영(SER8-TASKS B3).
- **USB 절전으로 재생 끊김(신규)** → `usbcore.autosuspend=-1`(부팅 영구 적용은 GRUB), fstab `nofail,noatime`.
- **SSD 미장착 부팅(신규)** → fstab `nofail` 로 부팅 차단 방지. 이때 앱은 자동으로 '(오프라인)' + YouTube 폴백으로 동작하므로 서비스는 계속된다.
- **YouTube 링크 부패/오매칭** → 링크는 캐시일 뿐, md 재생성으로 교체 용이. 플레이어에 "다른 영상 찾기(검색)" 버튼.
- **ser8 메모리 압박(신규)** → 가용 5.5GiB에서 coinbot 스택과 공존. 압박 시 `NEO4J_HEAP=512M`/`NEO4J_PAGECACHE=256M`, 그래도 부족하면 Neo4j·임베딩만 Ubuntu PC로 분리(계층이 나뉘어 있어 이동 쉬움).
