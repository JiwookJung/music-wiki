from __future__ import annotations

import argparse
import os
from pathlib import Path

from music_wiki.core.config import Config
from music_wiki.core.store import Store
from music_wiki.core.tags import MutagenTagReader
from music_wiki.core.wiki import WikiGenerator
from music_wiki.ingest.audio.scan import scan_library
from music_wiki.organize.apply import run_plan
from music_wiki.external.musicbrainz import HttpMusicBrainzClient
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.enrich import enrich_genres
from music_wiki.organize.pages import build_library_pages
from music_wiki.core.physical_wiki import generate_physical_wiki, write_home_index
from music_wiki.organize.plan import build_plan
from music_wiki.organize.review import export_review, import_review
from music_wiki.external.local_llm import OpenAICompatibleLLMClient
from music_wiki.organize.llm_classify import classify_low_confidence_llm
from music_wiki.organize.describe import describe_albums


def _store_at(db_path: str) -> Store:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store = Store.open(db_path)
    store.init_schema()
    return store


def _llm_client(cfg: Config) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(cfg.llm_base_url, cfg.llm_model,
                                     cache_dir=str(cfg.llm_cache_dir))


def _cmd_scan(args) -> int:
    store = _store_at(args.db)
    stats = scan_library(args.source, store, MutagenTagReader())
    print(f"scanned={stats.scanned} ingested={stats.ingested} "
          f"drm={stats.drm} skipped={stats.skipped} errors={stats.errors}")
    return 0


def _cmd_build_wiki(args) -> int:
    store = _store_at(args.db)
    WikiGenerator(store).generate(args.out)
    print(f"wiki written to {args.out}")
    return 0


def _cmd_classify(args) -> int:
    cfg = Config.default()
    store = _store_at(args.db)
    n = classify_albums(store)
    print(f"classified {n} albums (rules)")
    if args.enrich_genre:
        client = HttpMusicBrainzClient(cfg.musicbrainz_user_agent,
                                       cache_dir=str(cfg.mb_cache_dir))
        m = enrich_genres(store, client)
        print(f"enriched {m} albums via MusicBrainz")
    if args.classify_llm:
        k = classify_low_confidence_llm(store, _llm_client(cfg))
        print(f"classified {k} low-confidence albums via local LLM")
    return 0


def _cmd_describe(args) -> int:
    cfg = Config.default()
    store = _store_at(args.db)
    n = describe_albums(store, _llm_client(cfg), force=args.force, limit=args.limit)
    print(f"described {n} albums via local LLM ({cfg.llm_model})")
    return 0


def _cmd_review_export(args) -> int:
    store = _store_at(args.db)
    n = export_review(store, args.out, threshold=args.threshold)
    print(f"exported {n} albums to {args.out} (confidence < {args.threshold} or 미분류)")
    return 0


def _cmd_review_import(args) -> int:
    store = _store_at(args.db)
    n = import_review(store, args.in_path)
    print(f"applied {n} manual classifications")
    return 0


def _cmd_organize(args) -> int:
    store = _store_at(args.db)
    ops = build_plan(store, args.target)
    stats = run_plan(ops, store, dry_run=not args.apply)
    if args.apply:
        pages = build_library_pages(store)
        print(f"[APPLIED] planned={stats.planned} copied={stats.copied} "
              f"skipped={stats.skipped} errors={stats.errors} pages={pages}")
    else:
        would = stats.planned - stats.skipped - stats.errors
        print(f"[DRY-RUN] planned={stats.planned} would_copy={would} "
              f"already={stats.skipped} target={args.target}  (use --apply to copy)")
    return 0


def _cmd_build_pages(args) -> int:
    store = _store_at(args.db)
    n = build_library_pages(store, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[DRY-RUN] would write {n} album pages")
    else:
        print(f"wrote {n} album index.html pages")
    return 0


def _cmd_update(args) -> int:
    """원커맨드 갱신: 변경분 스캔 → 신규만 분류 → (실물 파이프라인) → md 위키."""
    import subprocess
    import sys as _sys
    from collections import Counter
    from pathlib import Path as _P

    from music_wiki.organize.buckets import classify_by_rules

    store = _store_at(args.db)
    report: list[str] = []

    # ① 스캔(멱등: 신규/변경 파일만)
    if not args.no_scan:
        stats = scan_library(args.source, store, MutagenTagReader())
        report.append(f"스캔: {stats.scanned}개 중 신규/변경 {stats.ingested}개 반영"
                      f" (DRM {stats.drm}, 오류 {stats.errors})")

    # ② 신규 앨범만 규칙 분류(기존 manual/claude 분류는 보존)
    n_new = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_bucket is not None:
                continue
            titles = [tr.title for tr in store.tracks_for_album(album.id)]
            res = classify_by_rules(album.genres, artist.name, titles, album=album.title)
            store.set_album_genre(album.id, res.bucket, res.confidence, "rule")
            n_new += 1
    report.append(f"신규 분류: {n_new}개 앨범(규칙)")

    # ③ 실물 인벤토리 파이프라인 + 디지털 연동 (있을 때만)
    inv = _P(__file__).resolve().parents[2] / "inventory" / "scripts"
    phys_json = inv.parent / "data" / "physical_albums.json"
    if not args.no_physical and (inv / "pipeline.py").exists():
        for script in ("pipeline.py", "link_digital.py"):
            r = subprocess.run([_sys.executable, str(inv / script)],
                               capture_output=True, text=True)
            tail = (r.stdout or r.stderr).strip().splitlines()
            report.append(f"{script}: " + (tail[-1] if tail else f"exit {r.returncode}"))

    # ④ md 위키 재생성 (디지털 + 실물 통합 + 홈)
    WikiGenerator(store).generate(args.out)
    counts = Counter()
    need_desc: list[str] = []
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            counts[album.genre_bucket or "미분류"] += 1
            if not album.description:
                need_desc.append(f"- [디지털] {artist.name} — {album.title}")
    if phys_json.exists():
        pstats = generate_physical_wiki(args.out, str(phys_json))
        report.append(f"실물 위키: 앨범 md {pstats['albums_created']}개, "
                      f"아티스트 {pstats['artists_touched']}명 반영")
        import json as _json
        for a in _json.load(open(phys_json, encoding="utf-8")):
            if not str(a.get("desc") or "").strip():
                need_desc.append(f"- [실물 {a['code']}] {a['artist']} — {a['album']}")
    write_home_index(args.out, dict(counts), str(phys_json) if phys_json.exists() else None)

    # ⑤ 해설 필요 목록(Claude에게 요청용)
    todo = _P(args.out) / "작업목록-해설필요.md"
    if need_desc:
        todo.write_text("# 해설 필요 앨범 (" + str(len(need_desc)) + "건)\n\n"
                        "Claude에게 '이 목록 해설 채워줘'라고 요청하세요.\n\n"
                        + "\n".join(need_desc) + "\n", encoding="utf-8")
        report.append(f"해설 필요: {len(need_desc)}건 → {todo}")
    elif todo.exists():
        todo.unlink()
        report.append("해설 필요: 0건")

    print("[update]")
    for line in report:
        print(" ·", line)
    return 0


def main(argv: list[str] | None = None) -> int:
    cfg = Config.default()
    parser = argparse.ArgumentParser(prog="music-wiki")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="스캔 → DB (멱등)")
    p_scan.add_argument("--source", default=str(cfg.source_dir))
    p_scan.add_argument("--db", default=str(cfg.db_path))
    p_scan.set_defaults(func=_cmd_scan)

    p_wiki = sub.add_parser("build-wiki", help="DB → 마크다운 위키")
    p_wiki.add_argument("--db", default=str(cfg.db_path))
    p_wiki.add_argument("--out", default=str(cfg.vault_dir))
    p_wiki.set_defaults(func=_cmd_build_wiki)

    p_classify = sub.add_parser("classify", help="앨범 장르 버킷 산출(규칙)")
    p_classify.add_argument("--db", default=str(cfg.db_path))
    p_classify.add_argument("--enrich-genre", action="store_true")
    p_classify.add_argument("--classify-llm", action="store_true")
    p_classify.set_defaults(func=_cmd_classify)

    p_describe = sub.add_parser("describe", help="앨범 한국어 해설 생성(로컬 LLM) → DB")
    p_describe.add_argument("--db", default=str(cfg.db_path))
    p_describe.add_argument("--force", action="store_true")
    p_describe.add_argument("--limit", type=int, default=None)
    p_describe.set_defaults(func=_cmd_describe)

    p_rexport = sub.add_parser("review-export", help="저신뢰·미분류 앨범 CSV 출력")
    p_rexport.add_argument("--db", default=str(cfg.db_path))
    p_rexport.add_argument("--out", default="review.csv")
    p_rexport.add_argument("--threshold", type=float, default=0.8)
    p_rexport.set_defaults(func=_cmd_review_export)

    p_rimport = sub.add_parser("review-import", help="수정된 장르 확정")
    p_rimport.add_argument("--db", default=str(cfg.db_path))
    p_rimport.add_argument("--in", dest="in_path", default="review.csv")
    p_rimport.set_defaults(func=_cmd_review_import)

    p_org = sub.add_parser("organize", help="장르 트리로 복사(기본 dry-run)")
    p_org.add_argument("--db", default=str(cfg.db_path))
    p_org.add_argument("--target", default=os.path.expanduser("~/music-library"))
    p_org.add_argument("--apply", action="store_true")
    p_org.set_defaults(func=_cmd_organize)

    p_pages = sub.add_parser("build-pages", help="앨범 폴더에 index.html (재)생성")
    p_pages.add_argument("--db", default=str(cfg.db_path))
    p_pages.add_argument("--dry-run", action="store_true")
    p_pages.set_defaults(func=_cmd_build_pages)

    p_upd = sub.add_parser("update", help="원커맨드 갱신: 변경분 스캔→분류→실물 연동→md 위키")
    p_upd.add_argument("--db", default=str(cfg.db_path))
    p_upd.add_argument("--source", default=str(cfg.source_dir))
    p_upd.add_argument("--out", default=str(cfg.vault_dir))
    p_upd.add_argument("--no-scan", action="store_true")
    p_upd.add_argument("--no-physical", action="store_true")
    p_upd.set_defaults(func=_cmd_update)

    args = parser.parse_args(argv)
    return args.func(args)
