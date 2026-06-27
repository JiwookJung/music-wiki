from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def _rec(path, hash_, artist="이문세", album="3집", title="소녀",
         track_no=7, disc_no=1):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=track_no,
        disc_no=disc_no, year=1987, label=None, genres=["Ballad"], duration_s=215.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_album_description_defaults_none_and_set():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description is None and album.description_source is None
    s.set_album_description(album.id, "잔잔한 발라드 명반.", "llm:qwen3-14b")
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description == "잔잔한 발라드 명반."
    assert album.description_source == "llm:qwen3-14b"
