from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    source_dir: Path
    vault_dir: Path
    db_path: Path
    summary_model: str = "claude-opus-4-8"
    musicbrainz_user_agent: str = "music-wiki/0.1 (https://github.com/JiwookJung/music-wiki)"
    llm_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "qwen3-14b"

    @property
    def mb_cache_dir(self) -> Path:
        return self.vault_dir / "mb-cache"

    @property
    def llm_cache_dir(self) -> Path:
        return self.vault_dir / "llm-cache"

    @classmethod
    def default(cls) -> "Config":
        vault = Path.home() / "music-wiki-vault"
        return cls(
            source_dir=Path("/mnt/win/memory/음악"),
            vault_dir=vault,
            db_path=vault / "music-wiki.db",
        )
