from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from music_wiki.core.store import Store

from .plan import CopyOp


@dataclass
class ApplyStats:
    planned: int = 0
    copied: int = 0
    skipped: int = 0
    errors: int = 0


def run_plan(ops: list[CopyOp], store: Store | None = None, *,
             dry_run: bool = True) -> ApplyStats:
    stats = ApplyStats(planned=len(ops))
    for op in ops:
        try:
            dst = Path(op.dst)
            if dst.exists() and dst.stat().st_size == os.path.getsize(op.src):
                stats.skipped += 1
                if store is not None:
                    store.set_organized_path(op.src, op.dst)
                continue
            if dry_run:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(op.src, dst)
            stats.copied += 1
            if store is not None:
                store.set_organized_path(op.src, op.dst)
        except Exception:
            stats.errors += 1
    return stats
