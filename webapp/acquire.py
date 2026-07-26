"""E2: 음반 구매 등록 + 분류번호 즉시 발급 + LLM(claude -p) 패널.

발급은 inventory/scripts/pipeline.py 의 레지스트리 로직을 재사용한다.
(기존 코드 불변 원칙 유지 — 새 아티스트는 이웃 사이 빈 번호로 삽입)

주의: 레지스트리 쓰기는 ser8(이 앱) 단독이 원칙. 백엔드 pipeline.py 는 읽기 전용 재현.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

INV = Path(os.environ.get("MW_INVENTORY", "/data/inventory"))
if not INV.exists():
    INV = Path(__file__).resolve().parents[1] / "inventory"
PIPELINE = INV / "scripts" / "pipeline.py"
REGISTRY = INV / "data" / "code_registry.json"
PENDING = INV / "data" / "pending_albums.json"   # ser8에서 등록 → 백엔드가 엑셀 반영


def _pipe():
    """pipeline.py 를 모듈로 로드(경로는 컨테이너/로컬 모두 지원)."""
    spec = importlib.util.spec_from_file_location("mw_pipeline", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.REGISTRY = str(REGISTRY)
    return mod


def issue_code(*, artist: str, album: str, genre: str, medium: str = "LP",
               composer: str = "", performer: str = "", location: str = "",
               label_cat: str = "", dry_run: bool = False) -> dict:
    """분류번호 발급. dry_run이면 레지스트리를 저장하지 않고 미리보기만."""
    p = _pipe()
    rows = p.extract(p.XLSX) if os.path.exists(p.XLSX) else []
    new_row = {"sheet": location or "LP중앙선반2열1층", "order": "", "medium": medium,
               "genre": genre, "artist": artist, "album": album, "rep": "",
               "composer": composer, "performer": performer, "label_cat": label_cat,
               "discogs_id": "", "mbid": "", "db_url": "", "desc": "", "notes": "신규 구매"}
    rows.append(new_row)
    reg = p.load_registry()
    if not reg["artists"] and not reg["composers"] and os.path.exists(p.XLSX):
        p.seed_registry_from_existing(rows, reg)
    warnings: list[str] = []
    albums, codes, _meta = p.assign_codes(rows, reg, warnings)
    key = (p.norm(artist), p.norm(album))
    code = codes.get(key, "")
    if not dry_run and code:
        json.dump(reg, open(REGISTRY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        pend = json.load(open(PENDING, encoding="utf-8")) if PENDING.exists() else []
        pend.append({**new_row, "code": code})
        PENDING.parent.mkdir(parents=True, exist_ok=True)
        json.dump(pend, open(PENDING, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"code": code, "warnings": warnings, "dry_run": dry_run,
            "pending_total": len(json.load(open(PENDING, encoding="utf-8")))
            if PENDING.exists() else 0}


def ask_claude(prompt: str, timeout: int = 120) -> str:
    """구독 Claude Code 헤드리스 호출. 전용 임시 작업디렉토리에서 최소 권한 실행."""
    exe = os.environ.get("CLAUDE_BIN", "claude")
    with tempfile.TemporaryDirectory(prefix="mw-llm-") as wd:
        try:
            r = subprocess.run([exe, "-p", prompt], cwd=wd, capture_output=True,
                               text=True, timeout=timeout)
        except FileNotFoundError:
            return "(Claude Code 미설치 — ser8에 `claude` CLI 설치 후 로그인 필요)"
        except subprocess.TimeoutExpired:
            return "(시간 초과)"
    return (r.stdout or r.stderr or "").strip()
