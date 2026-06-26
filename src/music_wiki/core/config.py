from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    source_dir: Path
    vault_dir: Path
    db_path: Path
    summary_model: str = "claude-opus-4-8"

    @classmethod
    def default(cls) -> "Config":
        vault = Path.home() / "music-wiki-vault"
        return cls(
            source_dir=Path("/mnt/win/memory/음악"),
            vault_dir=vault,
            db_path=vault / "music-wiki.db",
        )
