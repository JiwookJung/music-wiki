# ser8 마이그레이션 가이드

이 PC(개발/백엔드)에서 검증된 스택을 ser8 미니PC(24시간 프론트)로 옮기는 절차.
소요 시간 30~60분(다운로드 제외). 모든 서비스는 Docker 컨테이너라 OS 의존성이 거의 없다.

## 이관 순서 요약 (체크리스트)

| # | 단계 | 어디서 | 소요 |
|---|---|---|---|
| 0 | Ubuntu 설치 + Docker/git/rsync | ser8 | 20분 |
| 1 | 코드 clone + vault·엑셀 rsync (약 100MB) | 양쪽 | 5분 |
| 2 | `.env` 설정(비밀번호·경로) | ser8 | 2분 |
| 3 | `docker compose up -d` + 적재 3종 | ser8 | 10분 |
| 4 | **동작 확인** — 웹 열기, 재생, 발급 테스트 | ser8 | 5분 |
| 5 | (선택) mp3 NFS 마운트 → 원본 재생 | 양쪽 | 10분 |
| 6 | (선택) Tailscale — 외부/폰 접속 | ser8 | 5분 |
| 7 | (선택) WoL — ser8에서 백엔드 깨우기 | 양쪽 | 10분 |

**이 PC의 실측값** (2026-07-27 기준, 아래 명령에 그대로 사용):

| 항목 | 값 |
|---|---|
| 백엔드 IP | `192.168.50.112` |
| 백엔드 MAC (WoL) | `d8:bb:c1:59:7d:b3` |
| mp3 원본 | `/mnt/win/memory/음악` (170GB — **복사하지 않음**, NFS로 참조) |
| 옮길 데이터 | vault 97MB + 엑셀·인벤토리 3MB ≈ **100MB** |
| Neo4j 데이터 | 528MB — **복사 불필요**(ser8에서 재적재가 더 빠르고 깨끗) |

> 롤백: ser8에서 뭘 해도 이 PC의 원본·DB·엑셀은 그대로다. 실패하면 ser8만 다시 시작하면 된다.

## 0. 사전 준비 (ser8)

```bash
# Ubuntu Server/Desktop 22.04+ 설치 후
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git rsync
sudo usermod -aG docker $USER   # 재로그인 필요
```

## 1. 코드·데이터 가져오기

```bash
# 1) 코드 (GitHub)
git clone git@github.com:JiwookJung/music-wiki.git ~/music-wiki

# 2) vault (md 지식베이스 + SQLite + youtube_links) — 이 PC에서 실행
rsync -avz --exclude library/ ~/music-wiki-vault/ ser8:~/music-wiki-vault/
#    library/ 는 mp3 심볼릭 링크라 ser8에서 무의미 → 제외

# 3) 인벤토리 엑셀(정본) — 이 PC에서 실행
rsync -avz ~/lpcd_image/ ser8:~/lpcd_image/
```

## 2. 설정

```bash
cd ~/music-wiki/deploy
cp .env.example .env
vi .env
#   NEO4J_PASSWORD=<강한 비밀번호>
#   VAULT_DIR=/home/<user>/music-wiki-vault
#   INVENTORY_DIR=/home/<user>/music-wiki/inventory
#   MUSIC_DIR=/mnt/ubuntu-music        # 백엔드 NFS 마운트 지점(3번 참고)
```

## 3. 기동

```bash
docker compose up -d              # neo4j + web
docker compose ps                 # 둘 다 Up / neo4j healthy 확인

# 그래프 적재(최초 1회 + 데이터 갱신 시)
docker compose exec web python /app/scripts/build_catalog.py
docker compose exec web python /app/scripts/load_neo4j.py --wipe
docker compose exec web python /app/scripts/build_embeddings.py   # 유사검색(CPU 1분)
```

접속: `http://<ser8-IP>:8765` (Neo4j 브라우저는 `http://<ser8-IP>:7474`)

## 4. 동작 확인 (이관 성공 판정)

```bash
curl -s http://localhost:8765/api/status          # {"music_online":false,"tracks":15266}
#   music_online:false 는 정상 — 아직 mp3 마운트 전(5장에서 연결)
```

브라우저에서 `http://<ser8-IP>:8765` 접속 후 4가지만 확인하면 이관 완료:

1. **홈** — "합집합 카탈로그 1,950 앨범" 표시
2. **앨범 페이지** — YouTube 영상 재생 + "비슷한 앨범" 목록(임베딩 정상)
3. **📚 정리장** — 선반 16곳 목록(Neo4j 정상)
4. **➕ 등록** — 아무 이름이나 넣고 **미리보기** 클릭 → 코드가 나오면 발급 로직 정상
   (미리보기는 저장하지 않으므로 테스트해도 안전)

## 5. mp3 스트리밍 (ser8에서 Ubuntu 원본 재생)

앨범 페이지의 **수록곡 목록**을 클릭하면 원본 mp3가 스트리밍된다(Range 지원, 연속재생).
ser8에서는 Ubuntu의 원본을 NFS 등으로 마운트하고 `.env` 에 경로만 맞추면 된다:

```bash
# Ubuntu(백엔드)에서 export
sudo apt install nfs-kernel-server
echo '/mnt/win/memory/음악 <ser8-IP>(ro,sync,no_subtree_check)' | sudo tee -a /etc/exports
sudo exportfs -ra

# ser8에서 마운트 + .env
sudo mkdir -p /mnt/music && sudo mount -t nfs 192.168.50.112:/mnt/win/memory/음악 /mnt/music
echo 'MUSIC_DIR=/mnt/music' >> deploy/.env      # 컨테이너 /data/music 로 마운트됨
```

- `MW_MUSIC_SRC`(DB에 기록된 원본 루트) → `MW_MUSIC_MNT`(/data/music)로 자동 치환해 재생.
- **Ubuntu가 꺼져 있으면** 트랙이 "(오프라인)"으로 표시되고 YouTube 임베드로 계속 감상 가능.
- 백엔드 온라인 여부는 `GET /api/status` 로 확인(`music_online`).

## 6. 외부(휴대폰/외부망) 접속 — Tailscale

```bash
# Tailscale 어드민에서 auth key 발급 → .env 에 TS_AUTHKEY=tskey-...
docker compose --profile remote up -d
# 폰에 Tailscale 앱 설치·같은 계정 로그인 → https://musicwiki.<tailnet>.ts.net 접속
```

포트 개방·도메인·인증서 불필요. 홈 화면에 추가하면 PWA처럼 사용.

## 7. WoL — ser8에서 백엔드 깨우기

mp3 원본 재생이나 대량 배치가 필요할 때 ser8에서 Ubuntu를 원격 기동한다.
(mp3 마운트 자체는 5장에서 이미 설정)

```bash
# 1) Ubuntu BIOS/UEFI: Wake-on-LAN (또는 "Power On by PCI-E") 활성화
# 2) Ubuntu 에서 NIC 의 WoL 켜기(재부팅 후에도 유지하려면 systemd 서비스로 등록)
sudo apt install -y ethtool
sudo ethtool -s $(ip route | awk '/default/{print $5; exit}') wol g

# 3) ser8 에서 깨우기 — 이 PC의 MAC 은 d8:bb:c1:59:7d:b3
sudo apt install -y wakeonlan
wakeonlan d8:bb:c1:59:7d:b3
sleep 40 && curl -s http://localhost:8765/api/status   # music_online:true 면 성공
```

같은 서브넷(브로드캐스트 도달 가능)이어야 하며, 유선 연결에서만 안정적으로 동작한다.

## 8. 일상 운영

| 상황 | 명령 (실행 위치) |
|---|---|
| mp3 추가·태그 변경 | **Ubuntu**: `music-wiki update` → `git push` / **ser8**: `git pull` + vault rsync |
| 음반 구매(분류번호 발급) | **ser8 웹UI** `/add` → 즉시 코드 발급 + 대기큐 적재 → **Ubuntu에서 `music-wiki update`** 실행 시 엑셀·md·그래프까지 자동 반영(`apply_pending.py`가 큐를 소진) |
| 카탈로그·그래프 갱신 | **ser8**: `build_catalog.py` → `load_neo4j.py` → `build_embeddings.py` |
| YouTube 링크 보강 | **Ubuntu**(대량) 또는 ser8: `python scripts/resolve_youtube.py` |
| 스택 업데이트 | **ser8**: `git pull && docker compose build web && docker compose up -d` |

## 8-1. LLM 패널 (선택)

ser8에 Claude Code CLI 설치 + 로그인하면 `/ask` 에서 구독 계정으로 질의 가능:
```bash
curl -fsSL https://claude.ai/install.sh | sh   # 또는 npm i -g @anthropic-ai/claude-code
claude login
# compose 에서 CLAUDE_BIN 이 컨테이너 내 경로를 가리키도록 하거나,
# 호스트에서 `claude -p` 를 쓰는 경량 프록시를 두는 방식 중 택1 (E2 후속)
```

## 9. 역할 분담 요약

- **ser8(24h)**: 웹앱·Neo4j·조회/발급/원격접속. 데이터 사본 보유(vault/DB/inventory).
- **Ubuntu(온디맨드)**: mp3 원본 170GB, 무거운 배치(스캔·대량 해설), 에이전트 작업.
- **동기 매체**: GitHub(코드·inventory·registry) + rsync(vault) — 분류코드 레지스트리 쓰기는
  **ser8 단독**이 원칙(이중 발급 방지).

## 10. 트러블슈팅

- `mw-web` 이 뜨자마자 죽음 → `docker logs mw-web`; 대개 VAULT_DIR 경로 오타.
- 그래프 페이지가 "Neo4j 미연결" → `docker compose ps` 로 neo4j healthy 확인, `.env`
  비밀번호가 web/neo4j 양쪽 동일한지 확인.
- YouTube 임베드가 안 뜸 → 일부 영상은 임베드 금지. 페이지의 "YouTube 검색" 링크로 폴백.
- Neo4j 메모리 압박 → `.env` 의 `NEO4J_HEAP=512M`, `NEO4J_PAGECACHE=256M` 로 축소.
