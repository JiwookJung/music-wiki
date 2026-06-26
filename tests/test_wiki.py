from pathlib import Path
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.core.wiki import WikiGenerator, safe_filename


def _seed(store):
    store.upsert(TrackRecord(
        artist_name="IU", album_title="Lilac", track_title="Lilac",
        track_no=1, disc_no=None, year=2021, label="EDAM", genres=["K-Pop"],
        duration_s=215.0, cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    ))


def test_safe_filename_strips_separators():
    assert safe_filename("AC/DC: Live") == "AC_DC_ Live"


def test_generate_writes_artist_and_album_pages(tmp_path: Path):
    s = Store.open(":memory:")
    s.init_schema()
    _seed(s)
    WikiGenerator(s).generate(str(tmp_path))
    artist_md = (tmp_path / "artists" / "IU.md").read_text(encoding="utf-8")
    assert "[[IU - Lilac]]" in artist_md
    album_md = (tmp_path / "albums" / "IU - Lilac.md").read_text(encoding="utf-8")
    assert "[[IU]]" in album_md
    assert "디지털 보유" in album_md
    assert "Lilac" in album_md and "2021" in album_md
