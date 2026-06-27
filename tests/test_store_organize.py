from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def _rec(path, hash_, artist="IU", album="Lilac", title="Lilac", track_no=1, genres=None):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title,
        track_no=track_no, disc_no=None, year=2021, label="EDAM",
        genres=genres if genres is not None else ["Ballad"], duration_s=180.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_album_genre_columns_default_none_and_set():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket is None and album.genre_confidence is None
    s.set_album_genre(album.id, "가요", 0.9, "rule")
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "가요"
    assert album.genre_confidence == 0.9
    assert album.genre_source == "rule"


def test_iter_organizable_joins_non_drm_only():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    s.record_drm(SourceFile(abs_path="/x/a.enc", content_hash="d1", mtime=1.0,
                            fmt="enc", is_drm=True))
    rows = s.iter_organizable()
    assert len(rows) == 1
    r = rows[0]
    assert r.abs_path == "/x/1.mp3" and r.artist_name == "IU"
    assert r.album_title == "Lilac" and r.track_title == "Lilac" and r.track_no == 1


def test_iter_organizable_yields_one_row_per_source_file():
    s = _store()
    # two different files resolving to the SAME track (album/disc/track/title)
    s.upsert(_rec("/x/1.mp3", "h1"))
    s.upsert(_rec("/x/2.mp3", "h2"))
    rows = s.iter_organizable()
    assert {r.abs_path for r in rows} == {"/x/1.mp3", "/x/2.mp3"}


def test_set_organized_path():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    s.set_organized_path("/x/1.mp3", "/home/lib/가요/IU/Lilac/01 - Lilac.mp3")
    row = s.conn.execute(
        "SELECT organized_path FROM source_file WHERE abs_path=?", ("/x/1.mp3",)
    ).fetchone()
    assert row[0] == "/home/lib/가요/IU/Lilac/01 - Lilac.mp3"
