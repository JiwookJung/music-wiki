from pathlib import Path
from music_wiki.core.config import Config


def test_default_config_paths():
    cfg = Config.default()
    assert cfg.source_dir == Path("/mnt/win/memory/음악")
    assert cfg.vault_dir == Path.home() / "music-wiki-vault"
    assert cfg.db_path == cfg.vault_dir / "music-wiki.db"
    assert cfg.summary_model == "claude-opus-4-8"
