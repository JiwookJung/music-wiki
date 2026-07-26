from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.core.wiki import WikiGenerator


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def _rec():
    return TrackRecord(
        artist_name="Bill Evans", album_title="Waltz for Debby", track_title="T",
        track_no=1, disc_no=None, year=1961, label=None, genres=["Jazz"],
        duration_s=60.0, cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    )


def test_physical_code_column_and_vinyl_flag():
    s = _store()
    s.upsert(_rec())
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.physical_code is None
    s.set_physical_code(album.id, "LP J-B01-02")
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.physical_code == "LP J-B01-02"
    assert album.has_vinyl  # LP 코드는 바이닐 보유 표시


def test_wiki_renders_physical_code(tmp_path):
    s = _store()
    s.upsert(_rec())
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_physical_code(album.id, "LP J-B01-02")
    WikiGenerator(s).generate(str(tmp_path))
    md = next((tmp_path / "albums").glob("*.md")).read_text(encoding="utf-8")
    assert "실물 음반: LP J-B01-02" in md
