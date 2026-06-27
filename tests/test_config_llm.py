from pathlib import Path

from music_wiki.core.config import Config


def test_llm_defaults_and_cache_dir():
    cfg = Config(source_dir=Path("/src"), vault_dir=Path("/vault"),
                 db_path=Path("/vault/x.db"))
    assert cfg.llm_base_url == "http://localhost:1234/v1"
    assert cfg.llm_model == "qwen3-14b"
    assert cfg.llm_cache_dir == Path("/vault/llm-cache")


def test_llm_fields_overridable():
    cfg = Config(source_dir=Path("/s"), vault_dir=Path("/v"), db_path=Path("/v/x.db"),
                 llm_base_url="http://localhost:5000/v1", llm_model="gemma-3-12b")
    assert cfg.llm_base_url == "http://localhost:5000/v1"
    assert cfg.llm_model == "gemma-3-12b"
