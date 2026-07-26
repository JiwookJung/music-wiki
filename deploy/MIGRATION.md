# ser8 마이그레이션 가이드

이 PC(개발/백엔드)에서 검증된 스택을 ser8 미니PC(24시간 프론트)로 옮기는 절차.
소요 시간 30~60분(다운로드 제외). 모든 서비스는 Docker 컨테이너라 OS 의존성이 거의 없다.

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

## 4. 외부(휴대폰/외부망) 접속 — Tailscale

```bash
# Tailscale 어드민에서 auth key 발급 → .env 에 TS_AUTHKEY=tskey-...
docker compose --profile remote up -d
# 폰에 Tailscale 앱 설치·같은 계정 로그인 → https://musicwiki.<tailnet>.ts.net 접속
```

포트 개방·도메인·인증서 불필요. 홈 화면에 추가하면 PWA처럼 사용.

## 5. 백엔드(Ubuntu PC) 연동 — 선택

**mp3 스트리밍**(Ubuntu 켜져 있을 때만):
```bash
# Ubuntu PC
sudo apt install -y nfs-kernel-server
echo '/mnt/win/memory/음악 <ser8-IP>(ro,sync,no_subtree_check)' | sudo tee -a /etc/exports
sudo exportfs -ra
# ser8
sudo mkdir -p /mnt/ubuntu-music
sudo mount -t nfs <ubuntu-IP>:/mnt/win/memory/음악 /mnt/ubuntu-music
```

**WoL(원격 기동)**: Ubuntu BIOS에서 Wake-on-LAN 활성화 후
```bash
# ser8
sudo apt install -y wakeonlan
wakeonlan <ubuntu-MAC>
```

## 6. 일상 운영

| 상황 | 명령 (실행 위치) |
|---|---|
| mp3 추가·태그 변경 | **Ubuntu**: `music-wiki update` → `git push` / **ser8**: `git pull` + vault rsync |
| 음반 구매(분류번호 발급) | **ser8 웹UI**: `/add` 에서 입력 → 즉시 코드 발급(레지스트리 자동 갱신, `pending_albums.json` 대기목록) → 백엔드가 엑셀 반영 |
| 카탈로그·그래프 갱신 | **ser8**: `build_catalog.py` → `load_neo4j.py` → `build_embeddings.py` |
| YouTube 링크 보강 | **Ubuntu**(대량) 또는 ser8: `python scripts/resolve_youtube.py` |
| 스택 업데이트 | **ser8**: `git pull && docker compose build web && docker compose up -d` |

## 6-1. LLM 패널 (선택)

ser8에 Claude Code CLI 설치 + 로그인하면 `/ask` 에서 구독 계정으로 질의 가능:
```bash
curl -fsSL https://claude.ai/install.sh | sh   # 또는 npm i -g @anthropic-ai/claude-code
claude login
# compose 에서 CLAUDE_BIN 이 컨테이너 내 경로를 가리키도록 하거나,
# 호스트에서 `claude -p` 를 쓰는 경량 프록시를 두는 방식 중 택1 (E2 후속)
```

## 7. 역할 분담 요약

- **ser8(24h)**: 웹앱·Neo4j·조회/발급/원격접속. 데이터 사본 보유(vault/DB/inventory).
- **Ubuntu(온디맨드)**: mp3 원본 170GB, 무거운 배치(스캔·대량 해설), 에이전트 작업.
- **동기 매체**: GitHub(코드·inventory·registry) + rsync(vault) — 분류코드 레지스트리 쓰기는
  **ser8 단독**이 원칙(이중 발급 방지).

## 8. 트러블슈팅

- `mw-web` 이 뜨자마자 죽음 → `docker logs mw-web`; 대개 VAULT_DIR 경로 오타.
- 그래프 페이지가 "Neo4j 미연결" → `docker compose ps` 로 neo4j healthy 확인, `.env`
  비밀번호가 web/neo4j 양쪽 동일한지 확인.
- YouTube 임베드가 안 뜸 → 일부 영상은 임베드 금지. 페이지의 "YouTube 검색" 링크로 폴백.
- Neo4j 메모리 압박 → `.env` 의 `NEO4J_HEAP=512M`, `NEO4J_PAGECACHE=256M` 로 축소.
