# ser8 작업 체크리스트

ser8 미니PC 앞에서 **위에서부터 순서대로** 실행하며 체크하는 작업지시서.
원리·대안 설명은 [MIGRATION.md](MIGRATION.md), 전체 설계는
[../docs/superpowers/specs/2026-07-27-ser8-two-tier-expansion-design.md](../docs/superpowers/specs/2026-07-27-ser8-two-tier-expansion-design.md).

## 준비물

| 항목 | 값 |
|---|---|
| 백엔드(현 Ubuntu PC) IP | `192.168.50.112` |
| 백엔드 MAC (WoL용) | `d8:bb:c1:59:7d:b3` |
| 백엔드 mp3 원본 | `/mnt/win/memory/음악` (170GB, 복사 안 함) |
| GitHub | `git@github.com:JiwookJung/music-wiki.git` |
| 옮길 데이터 | vault 97MB + 엑셀 3MB ≈ **100MB** |
| ser8 사양 | 16GB RAM / 320GB — 스택 전체 40GB 미만이라 여유 |

> **안전**: ser8에서 무엇을 하든 백엔드의 mp3·DB·엑셀 원본은 손대지 않는다.
> 실패하면 ser8만 다시 시작하면 된다.

---

## A. 필수 (여기까지 하면 24시간 서비스 완성 · 약 40분)

### A1. OS·도구 설치 — ser8

- [ ] Ubuntu Server 또는 Desktop 22.04+ 설치, 네트워크 연결(**유선 권장** — WoL·NFS 안정성)
- [ ] 고정 IP 또는 공유기에서 DHCP 예약 설정 (매번 주소가 바뀌면 불편)
- [ ] 패키지 설치

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git rsync curl
sudo usermod -aG docker $USER
newgrp docker          # 또는 재로그인
docker run --rm hello-world    # 정상 출력되면 OK
```

- [ ] 절전 방지(24시간 가동이므로)

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

### A2. SSH 키 — ser8 → GitHub·백엔드

- [ ] 키 생성 후 GitHub에 등록

```bash
ssh-keygen -t ed25519 -C "ser8"      # 엔터 3번
cat ~/.ssh/id_ed25519.pub            # 출력을 GitHub → Settings → SSH keys 에 추가
ssh -T git@github.com                # "successfully authenticated" 확인
```

- [ ] 백엔드로도 접속되게(rsync·WoL 확인용): 백엔드에서
      `ssh-copy-id <ser8-user>@<ser8-IP>` 를 실행하거나 위 공개키를 백엔드
      `~/.ssh/authorized_keys` 에 추가

### A3. 코드·데이터 가져오기

- [ ] **ser8**: 코드 clone

```bash
git clone git@github.com:JiwookJung/music-wiki.git ~/music-wiki
```

- [ ] **백엔드(현 PC)**: vault·엑셀 전송 (`ser8` 부분은 실제 호스트명/IP로)

```bash
rsync -avz --exclude library/ ~/music-wiki-vault/ ser8:~/music-wiki-vault/
rsync -avz ~/lpcd_image/ ser8:~/lpcd_image/
```

- [ ] **ser8**: 도착 확인 — `du -sh ~/music-wiki-vault` 가 약 97MB

### A4. 설정

- [ ] `deploy/.env` 작성

```bash
cd ~/music-wiki/deploy
cp .env.example .env 2>/dev/null || true
cat >> .env <<'EOF'
NEO4J_PASSWORD=<강한-비밀번호로-교체>
VAULT_DIR=/home/<user>/music-wiki-vault
INVENTORY_DIR=/home/<user>/music-wiki/inventory
MUSIC_DIR=/mnt/ubuntu-music
WEB_PORT=8765
EOF
vi .env      # <user>, 비밀번호 실제 값으로 수정
```

- [ ] 엑셀 정본 경로 확인: `inventory/scripts/pipeline.py` 는 `~/lpcd_image/...`
      를 먼저 찾고 없으면 repo 사본을 쓴다. A3에서 lpcd_image 를 보냈으면 그대로 두면 된다.

### A5. 기동·적재

```bash
cd ~/music-wiki/deploy
docker compose up -d
docker compose ps                     # neo4j healthy, web Up 확인

docker compose exec web python /app/scripts/build_catalog.py      # 카탈로그 1,950
docker compose exec web python /app/scripts/load_neo4j.py --wipe  # 그래프
docker compose exec web python /app/scripts/build_embeddings.py   # 유사검색(CPU 1분)
```

- [ ] 세 명령 모두 오류 없이 완료

### A6. 동작 확인 (이관 성공 판정)

```bash
curl -s http://localhost:8765/api/status
# {"music_online":false,"tracks":15266}  ← music_online:false 는 정상(B1에서 연결)
```

브라우저 `http://<ser8-IP>:8765` 에서:

- [ ] **홈** — "합집합 카탈로그 1,950 앨범"
- [ ] **앨범 페이지** — YouTube 재생 + "비슷한 앨범" 표시(임베딩 정상)
- [ ] **📚 정리장** — 선반 16곳(Neo4j 정상)
- [ ] **➕ 등록** — 아무 이름 입력 → **미리보기** 클릭 → `LP-...` 코드 표시
      (미리보기는 저장하지 않으므로 테스트 안전)
- [ ] **💬 질의** — (C1 전에는 "Claude Code 미설치" 메시지가 정상)

### A7. 자동 시작

```bash
# compose 에 restart: unless-stopped 가 이미 있으므로 Docker 자동시작만 확인
sudo systemctl enable docker
sudo reboot          # 재부팅 후 http://<ser8-IP>:8765 가 저절로 뜨면 완료
```

- [ ] 재부팅 후 웹 자동 기동 확인

---

## B. 권장 (원본 재생·외부 접속 · 약 20분)

### B1. mp3 스트리밍 (NFS)

- [ ] **백엔드**: export 설정

```bash
sudo apt install -y nfs-kernel-server
echo '/mnt/win/memory/음악 <ser8-IP>(ro,sync,no_subtree_check)' | sudo tee -a /etc/exports
sudo exportfs -ra
```

- [ ] **ser8**: 마운트 + 부팅 시 자동 마운트

```bash
sudo apt install -y nfs-common
sudo mkdir -p /mnt/ubuntu-music
sudo mount -t nfs 192.168.50.112:/mnt/win/memory/음악 /mnt/ubuntu-music
ls /mnt/ubuntu-music | head          # Music, lp, melon 등이 보이면 성공

# 백엔드가 꺼져 있어도 부팅이 멈추지 않도록 soft·bg 옵션 필수
echo '192.168.50.112:/mnt/win/memory/음악 /mnt/ubuntu-music nfs ro,soft,bg,noauto,x-systemd.automount 0 0' \
  | sudo tee -a /etc/fstab
```

- [ ] `docker compose up -d` 재기동 후 앨범 페이지에서 **수록곡 클릭 → 재생**
- [ ] `curl -s http://localhost:8765/api/status` → `"music_online":true`

### B2. 외부·휴대폰 접속 (Tailscale)

- [ ] https://login.tailscale.com/admin/settings/keys 에서 auth key 발급
- [ ] `deploy/.env` 에 `TS_AUTHKEY=tskey-...` 추가

```bash
docker compose --profile remote up -d
```

- [ ] 폰에 Tailscale 앱 설치·같은 계정 로그인 →
      `https://musicwiki.<tailnet>.ts.net` 접속 확인 (홈 화면에 추가하면 앱처럼 사용)

### B3. WoL — ser8에서 백엔드 깨우기

- [ ] **백엔드 BIOS/UEFI**: Wake-on-LAN(또는 "Power On by PCI-E") 활성화
- [ ] **백엔드**: NIC WoL 켜기

```bash
sudo apt install -y ethtool
sudo ethtool -s $(ip route | awk '/default/{print $5; exit}') wol g
```

- [ ] **ser8**: 깨우기 테스트

```bash
sudo apt install -y wakeonlan
wakeonlan d8:bb:c1:59:7d:b3
sleep 40 && curl -s http://localhost:8765/api/status   # music_online:true 면 성공
```

---

## C. 선택 (LLM 패널)

### C1. Claude Code 설치 — `/ask` 활성화

- [ ] ser8에 설치·로그인 (구독 계정)

```bash
curl -fsSL https://claude.ai/install.sh | sh     # 또는 npm i -g @anthropic-ai/claude-code
claude login
claude -p "테스트: OK 한 단어로"                  # 응답 오면 정상
```

- [ ] 웹앱이 `claude` 를 호출할 수 있게 연결
      (현재 컨테이너 안에는 CLI가 없다. 둘 중 하나를 택한다)
      - **간단**: 웹앱을 컨테이너 대신 호스트에서 실행
        (`cd ~/music-wiki/webapp && uvicorn app:app --host 0.0.0.0 --port 8765`)
      - **권장**: 호스트에 작은 프록시를 두고 `CLAUDE_BIN` 을 그쪽으로 지정
        (E2 후속 작업 — 필요해지면 구현)

---

## D. 이관 후 일상 운영

| 상황 | 어디서 | 명령 |
|---|---|---|
| 음반 구매 | **ser8** | 웹 `/add` → 분류번호 발급(즉시) |
| 구매분 확정 | 백엔드 | `music-wiki update` (엑셀·md·그래프까지 자동) |
| mp3 추가 | 백엔드 | 파일 넣고 `music-wiki update` → `git push` |
| ser8 동기화 | ser8 | `git pull` + 백엔드에서 vault rsync |
| 카탈로그·그래프 갱신 | ser8 | `build_catalog.py` → `load_neo4j.py` → `build_embeddings.py` |
| 스택 업데이트 | ser8 | `git pull && docker compose build web && docker compose up -d` |

**원칙**: 분류번호 **발급은 ser8 단독**(이중 발급 방지). 백엔드는 큐를 소진하는 역할.

---

## E. 문제 해결

| 증상 | 확인 |
|---|---|
| web 컨테이너가 바로 죽음 | `docker logs mw-web` — 대개 `VAULT_DIR` 경로 오타 |
| "Neo4j 미연결" | `docker compose ps` healthy 확인, `.env` 비밀번호 web/neo4j 동일한지 |
| 수록곡이 전부 "(오프라인)" | 백엔드 켜짐? `ls /mnt/ubuntu-music` 로 마운트 확인 |
| YouTube 임베드 안 뜸 | 일부 영상은 임베드 금지 — 페이지의 "YouTube 검색" 링크로 폴백 |
| Neo4j 메모리 압박 | `.env` 에 `NEO4J_HEAP=512M`, `NEO4J_PAGECACHE=256M` |
| 부팅이 NFS에서 멈춤 | fstab 에 `soft,bg,noauto,x-systemd.automount` 옵션 있는지 |
