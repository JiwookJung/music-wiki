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
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.plan import build_plan
from music_wiki.organize.review import export_review, import_review


def _store_at(db_path: str) -> Store:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store = Store.open(db_path)
    store.init_schema()
    return store


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
    store = _store_at(args.db)
    n = classify_albums(store)
    print(f"classified {n} albums (rules)")
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
        print(f"[APPLIED] planned={stats.planned} copied={stats.copied} "
              f"skipped={stats.skipped} errors={stats.errors}")
    else:
        would = stats.planned - stats.skipped - stats.errors
        print(f"[DRY-RUN] planned={stats.planned} would_copy={would} "
              f"already={stats.skipped} target={args.target}  (use --apply to copy)")
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
    p_classify.set_defaults(func=_cmd_classify)

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

    args = parser.parse_args(argv)
    return args.func(args)
