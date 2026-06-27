from pathlib import Path

import music_wiki.cli as cli
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


class FakeLLM:
    model = "fake-model"

    def complete(self, system, user, *, json_schema=None):
        # classify path asks for json; describe path asks for prose
        if json_schema is not None:
            return '{"bucket": "재즈", "confidence": 0.95, "reasoning": "스윙"}'
        return "한국어 해설 본문."


def _seed(db: Path):
    s = Store.open(str(db))
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="미상", album_title="미상앨범", track_title="곡", track_no=1,
        disc_no=None, year=2000, label=None, genres=["#JUNK"], duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    ))


def test_classify_llm_flag_invokes_llm(tmp_path, monkeypatch):
    db = tmp_path / "w.db"
    _seed(db)
    monkeypatch.setattr(cli, "_llm_client", lambda cfg: FakeLLM())
    assert cli.main(["classify", "--db", str(db), "--classify-llm"]) == 0
    s = Store.open(str(db))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "재즈" and album.genre_source == "llm"


def test_describe_command_writes_description(tmp_path, monkeypatch):
    db = tmp_path / "w.db"
    _seed(db)
    monkeypatch.setattr(cli, "_llm_client", lambda cfg: FakeLLM())
    assert cli.main(["describe", "--db", str(db)]) == 0
    s = Store.open(str(db))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description == "한국어 해설 본문."
    assert album.description_source == "llm:fake-model"
