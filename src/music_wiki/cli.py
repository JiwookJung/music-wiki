from __future__ import annotations

import argparse
from pathlib import Path

from music_wiki.core.config import Config
from music_wiki.core.store import Store
from music_wiki.core.tags import MutagenTagReader
from music_wiki.core.wiki import WikiGenerator
from music_wiki.ingest.audio.scan import scan_library


def _store_at(db_path: str) -> Store:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store = Store.open(db_path)
    store.init_schema()
    return store


def _cmd_scan(args) -> int:
    store = _store_at(args.db)
    stats = scan_library(args.source, store, MutagenTagReader())
    print(f"scanned={stats.scanned} ingested={stats.ingested} "
          f"drm={stats.drm} skipped={stats.skipped}")
    return 0


def _cmd_build_wiki(args) -> int:
    store = _store_at(args.db)
    WikiGenerator(store).generate(args.out)
    print(f"wiki written to {args.out}")
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

    args = parser.parse_args(argv)
    return args.func(args)
