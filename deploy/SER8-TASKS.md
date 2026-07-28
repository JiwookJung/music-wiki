# ser8 작업 체크리스트

ser8 미니PC 앞에서 **위에서부터 순서대로** 실행하며 체크하는 작업지시서.
배경·대안은 [MIGRATION.md](MIGRATION.md), 전체 설계는
[../docs/superpowers/specs/2026-07-27-ser8-two-tier-expansion-design.md](../docs/superpowers/specs/2026-07-27-ser8-two-tier-expansion-design.md).

## 구조 (2026-07-28 확정)

**ser8 단독 운영.** 웹·그래프·재생·발급·에이전트를 전부 ser8이 맡고,
mp3는 **1TB 외장 SSD**로 직결한다 → **NFS·WoL 불필요**.
현 Ubuntu PC는 **NTFS 원본 백업 보관소**로만 남기고 평소 꺼둬도 된다.

```
[ser8 · 24시간]                          [Ubuntu PC · 평소 꺼둠]
  Docker: web + neo4j (+tailscale)         NTFS 5.8TB 원본 170GB
  + 외장 SSD 1TB (mp3 170GB)   ← USB 직결   = 백업 사본 (지우지 말 것)
  + vault·SQLite·registry                  GPU 2장 (로컬 LLM 등 선택)
```

## 준비물

| 항목 | 값 |
|---|---|
| GitHub | `git@github.com:JiwookJung/music-wiki.git` |
| 옮길 데이터 | vault 97MB + 엑셀 3MB ≈ **100MB** (+ SSD의 mp3 170GB) |
| SSD 라벨 | `MUSIC` (ext4) — mp3는 SSD의 `media/` 폴더 안 |
| ser8 사양 | 16GB RAM / 320GB — 스택 40GB 미만이라 여유 |
| 현 Ubuntu PC | `192.168.50.112` (백업용, 필요 시에만) |

> **안전**: ser8에서 무엇을 하든 이 PC의 NTFS 원본은 읽기전용이라 손상되지 않는다.
> 실패하면 ser8만 다시 시작하면 된다.

---

## A. 필수 (약 40분 — 여기까지 하면 24시간 서비스 완성)

### A1. OS·도구 설치

- [ ] Ubuntu Server/Desktop 22.04+ 설치, **유선 네트워크** 연결
- [ ] 공유기에서 고정 IP(DHCP 예약) 설정
- [ ] 패키지 설치

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git rsync curl
sudo usermod -aG docker $USER
newgrp docker
docker run --rm hello-world          # 정상 출력이면 OK
```

- [ ] 절전 방지 (24시간 가동)

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

### A2. SSH 키 → GitHub

```bash
ssh-keygen -t ed25519 -C "ser8"      # 엔터 3번
cat ~/.ssh/id_ed25519.pub            # GitHub → Settings → SSH keys 에 등록
ssh -T git@github.com                # "successfully authenticated" 확인
```

- [ ] GitHub 인증 성공
- [ ] (선택) 이 PC에서 rsync 하려면 ser8 접속도 열어두기
      — 이 PC에서 `ssh-copy-id <ser8-user>@<ser8-IP>`

### A3. 외장 SSD 연결 (mp3 170GB)

> SSD 포맷·복사는 **이 PC에서 이미 완료**. ser8에서는 꽂고 마운트만 하면 된다.

```bash
lsblk -f | grep MUSIC                 # LABEL=MUSIC 보이면 인식됨
sudo mkdir -p /mnt/music
echo 'LABEL=MUSIC /mnt/music ext4 defaults,nofail,noatime 0 2' | sudo tee -a /etc/fstab
sudo mount -a
ls /mnt/music/media | head            # Music, lp, melon … 보이면 성공
```

- [ ] `ls /mnt/music/media` 에 음악 폴더들이 보임
- [ ] fstab 에 **`nofail`** 확인 — SSD를 빼도 부팅이 멈추지 않음
- [ ] USB 절전 해제 (재생 중 끊김 방지)

```bash
echo -1 | sudo tee /sys/module/usbcore/parameters/autosuspend
# 영구 적용: /etc/default/grub 의 GRUB_CMDLINE_LINUX_DEFAULT 에
#   usbcore.autosuspend=-1 추가 후  sudo update-grub
```

### A4. 코드·데이터 가져오기

- [ ] **ser8**: 코드 clone

```bash
git clone git@github.com:JiwookJung/music-wiki.git ~/music-wiki
```

- [ ] **이 PC**: vault·엑셀 전송 (`ser8` 은 실제 호스트명/IP로)

```bash
rsync -avz --exclude library/ ~/music-wiki-vault/ ser8:~/music-wiki-vault/
rsync -avz ~/lpcd_image/ ser8:~/lpcd_image/
```

- [ ] **ser8**: `du -sh ~/music-wiki-vault` 가 약 97MB

### A5. 설정 (`deploy/.env`)

```bash
cd ~/music-wiki/deploy
cp .env.example .env
vi .env
```

아래 5줄을 실제 값으로 채운다:

```ini
NEO4J_PASSWORD=<강한-비밀번호>
VAULT_DIR=/home/<user>/music-wiki-vault
INVENTORY_DIR=/home/<user>/music-wiki/inventory
MUSIC_DIR=/mnt/music/media          # ← SSD 안의 음악 폴더 (컨테이너 /data/music 로 연결)
WEB_PORT=8765
```

> **`MUSIC_SRC` 는 건드리지 말 것.** DB에 기록된 원본 경로(`/mnt/win/memory/음악`)
> 를 가리키는 고정값이며, 이걸 `MUSIC_DIR` 로 치환해 재생한다. 재스캔하지 않는 한 그대로 둔다.

- [ ] `.env` 5줄 작성 완료

### A6. 기동·적재

```bash
cd ~/music-wiki/deploy
docker compose up -d
docker compose ps                    # neo4j healthy / web Up

docker compose exec web python /app/scripts/build_catalog.py      # 카탈로그 1,950
docker compose exec web python /app/scripts/load_neo4j.py --wipe  # 그래프
docker compose exec web python /app/scripts/build_embeddings.py   # 유사검색(CPU ~1분)
```

- [ ] 세 명령 모두 오류 없이 완료

### A7. 동작 확인 (이관 성공 판정)

```bash
curl -s http://localhost:8765/api/status
# {"music_online":true,"tracks":15266}   ← true 여야 SSD 정상
```

브라우저 `http://<ser8-IP>:8765` 에서 5가지 확인:

- [ ] **홈** — "합집합 카탈로그 1,950 앨범"
- [ ] **앨범 페이지** — YouTube 재생 + "비슷한 앨범"(임베딩 정상)
- [ ] **수록곡 클릭 → 원본 mp3 재생** (SSD 정상)
- [ ] **📚 정리장** — 선반 16곳(Neo4j 정상)
- [ ] **➕ 등록** — 이름 입력 후 **미리보기** → `LP-...` 코드 표시 (저장 안 되므로 안전)

### A8. 자동 시작

```bash
sudo systemctl enable docker
sudo reboot
```

- [ ] 재부팅 후 `http://<ser8-IP>:8765` 가 저절로 뜸
- [ ] `curl -s http://localhost:8765/api/status` → `music_online:true` (SSD 자동 마운트 확인)

---

## B. 권장 (약 10분)

### B1. 외부·휴대폰 접속 (Tailscale)

- [ ] https://login.tailscale.com/admin/settings/keys 에서 auth key 발급
- [ ] `deploy/.env` 에 `TS_AUTHKEY=tskey-...` 추가

```bash
docker compose --profile remote up -d
```

- [ ] 폰에 Tailscale 앱 설치·같은 계정 로그인 →
      `https://musicwiki.<tailnet>.ts.net` 접속 (홈 화면에 추가하면 앱처럼 사용)

### B2. LLM 연결 — 웹 `/ask` + 향후 에이전트

> ser8은 **GPU가 없어** 로컬 LLM(Qwen 14B 등)은 CPU로 너무 느리다.
> **Claude Code 구독 헤드리스가 권장 경로**(추가 과금 없음).

```bash
curl -fsSL https://claude.ai/install.sh | sh     # 또는 npm i -g @anthropic-ai/claude-code
claude login
claude -p "테스트: OK 한 단어로"                  # 응답 오면 정상
```

- [ ] `claude -p` 응답 확인
- [ ] 웹앱에서 호출되게 연결 — 둘 중 택1
      - **간단**: 웹앱을 컨테이너 대신 호스트에서 실행
        (`cd ~/music-wiki/webapp && uvicorn app:app --host 0.0.0.0 --port 8765`)
      - **대안**: 로컬 LLM이 꼭 필요하면 이 PC(GPU 2장)에 LM Studio를 띄우고
        ser8에서 `LLM_BASE_URL=http://192.168.50.112:1234/v1` 로 호출 (이 PC 켜야 함)

### B3. 백업 습관

- [ ] mp3를 ser8에서 추가했다면 가끔 이 PC 원본에도 반영

```bash
# 이 PC에서 (SSD를 잠시 연결하거나 네트워크로)
rsync -a <ser8>:/mnt/music/media/ /mnt/ssd-backup/
```

- [ ] `git push` 로 코드·inventory·registry 백업 (GitHub이 사실상 백업본)

---

## C. 일상 운영 (전부 ser8에서)

| 상황 | 명령 |
|---|---|
| 음반 구매 | 웹 `/add` → 분류번호 즉시 발급 |
| 구매분 확정 | `music-wiki update` (엑셀·md·그래프까지 자동) |
| mp3 추가 | `/mnt/music/media/` 에 넣고 `music-wiki update` |
| 카탈로그·그래프 갱신 | `build_catalog.py` → `load_neo4j.py` → `build_embeddings.py` |
| 스택 업데이트 | `git pull && docker compose build web && docker compose up -d` |
| 백업 | `git push` |

**원칙**: 모든 쓰기(발급·스캔·갱신)는 **ser8 단독**. 이 PC는 원본 백업 보관소.

---

## D. 문제 해결

| 증상 | 확인 |
|---|---|
| web 컨테이너가 바로 죽음 | `docker logs mw-web` — 대개 `VAULT_DIR` 오타 |
| "Neo4j 미연결" | `docker compose ps` healthy 확인, `.env` 비밀번호 web/neo4j 동일한지 |
| 곡이 전부 "(오프라인)" | `ls /mnt/music/media` 확인, `.env` 의 `MUSIC_DIR=/mnt/music/media` 인지 |
| 재생 중 갑자기 끊김 | USB 절전 — `cat /sys/module/usbcore/parameters/autosuspend` 가 `-1` 인지 |
| SSD 없이 부팅 실패 | fstab 에 `nofail` 있는지 (복구 모드에서 추가) |
| YouTube 임베드 안 뜸 | 일부 영상은 임베드 금지 — 페이지의 "YouTube 검색" 링크로 폴백 |
| Neo4j 메모리 압박 | `.env` 에 `NEO4J_HEAP=512M`, `NEO4J_PAGECACHE=256M` |
| 경로 치환이 헷갈릴 때 | DB엔 `/mnt/win/memory/음악/...` 기록 → 컨테이너가 `MW_MUSIC_SRC`(그 경로)를 `/data/music` 으로 치환 → `/data/music` 은 `MUSIC_DIR`(=`/mnt/music/media`) 마운트 |
