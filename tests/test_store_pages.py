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


def test_iter_organized_groups_and_carries_metadata():
    s = _store()
    s.upsert(_rec("/src/7.mp3", "h1", title="소녀", track_no=7))
    s.upsert(_rec("/src/8.mp3", "h2", title="그늘", track_no=8))
    assert s.iter_organized() == []  # nothing organized yet
    s.set_organized_path("/src/7.mp3", "/lib/가요/이문세/3집/1-07 - 소녀.mp3")
    s.set_organized_path("/src/8.mp3", "/lib/가요/이문세/3집/1-08 - 그늘.mp3")
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "가요", 0.9, "rule")
    s.set_album_description(album.id, "해설입니다.", "llm:x")
    rows = s.iter_organized()
    assert len(rows) == 2
    r = rows[0]
    assert r.artist_name == "이문세" and r.album_title == "3집"
    assert r.album_year == 1987 and r.genre_bucket == "가요"
    assert r.description == "해설입니다." and r.duration_s == 215.0
    assert {x.track_no for x in rows} == {7, 8}


def test_iter_organized_excludes_drm_and_unorganized():
    s = _store()
    s.upsert(_rec("/src/7.mp3", "h1"))  # organized_path stays NULL
    s.record_drm(SourceFile(abs_path="/src/a.enc", content_hash="d1", mtime=1.0,
                            fmt="enc", is_drm=True))
    assert s.iter_organized() == []
