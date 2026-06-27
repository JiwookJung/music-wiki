from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def _rec(path, hash_, artist="IU", album="Lilac", title="Lilac", track_no=1, year=2021):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title,
        track_no=track_no, disc_no=None, year=year, label="EDAM",
        genres=["K-Pop"], duration_s=180.0, cover_path="/x/cover.jpg",
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_upsert_creates_artist_album_track():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    artists = s.iter_artists()
    assert [a.name for a in artists] == ["IU"]
    albums = s.albums_for_artist(artists[0].id)
    assert albums[0].title == "Lilac"
    assert albums[0].has_digital is True and albums[0].has_vinyl is False
    assert albums[0].genres == ["K-Pop"]
    tracks = s.tracks_for_album(albums[0].id)
    assert [t.title for t in tracks] == ["Lilac"]


def test_upsert_is_idempotent_on_content_hash():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    s.upsert(_rec("/x/1.mp3", "h1"))  # same file, second run
    assert len(s.tracks_for_album(s.albums_for_artist(s.iter_artists()[0].id)[0].id)) == 1


def test_dedup_artist_by_case_insensitive_key():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", artist="The Beatles"))
    s.upsert(_rec("/x/2.mp3", "h2", artist="the beatles", title="B", track_no=2))
    assert len(s.iter_artists()) == 1


def test_record_drm():
    s = _store()
    s.record_drm(SourceFile(abs_path="/x/a.enc", content_hash="d1", mtime=1.0,
                            fmt="enc", is_drm=True))
    assert s.drm_count() == 1


def test_album_and_track_dedup_case_insensitive():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", album="Lilac", title="Lilac", track_no=1))
    s.upsert(_rec("/x/2.mp3", "h2", album="lilac", title="lilac", track_no=1))
    albums = s.albums_for_artist(s.iter_artists()[0].id)
    assert len(albums) == 1
    assert len(s.tracks_for_album(albums[0].id)) == 1


def test_upsert_fills_null_year_via_coalesce():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", title="A", track_no=1, year=None))
    s.upsert(_rec("/x/2.mp3", "h2", title="B", track_no=2, year=2021))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.year == 2021


def test_changed_file_reupsert_prunes_stale_rows():
    s = _store()
    s.upsert(_rec("/x/song.mp3", "h1", artist="Old", album="OldAlbum", title="OldTitle"))
    # same path, new hash (changed file), different metadata
    s.upsert(_rec("/x/song.mp3", "h2", artist="New", album="NewAlbum", title="NewTitle"))
    assert [a.name for a in s.iter_artists()] == ["New"]  # old artist GC'd
    assert s.conn.execute(
        "SELECT COUNT(*) FROM source_file WHERE abs_path=?", ("/x/song.mp3",)
    ).fetchone()[0] == 1
    assert s.conn.execute("SELECT COUNT(*) FROM track").fetchone()[0] == 1


def test_drm_files_lists_paths():
    s = _store()
    s.record_drm(SourceFile(abs_path="/x/a.enc", content_hash="d1", mtime=1.0,
                            fmt="enc", is_drm=True))
    assert s.drm_files() == ["/x/a.enc"]


def test_prune_keeps_album_shared_with_another_file():
    s = _store()
    # two tracks of the same album, from different files
    s.upsert(_rec("/x/t1.mp3", "h1", artist="A", album="Alb", title="T1", track_no=1))
    s.upsert(_rec("/x/t2.mp3", "h2", artist="A", album="Alb", title="T2", track_no=2))
    # re-ingest t1 as a CHANGED file (new hash) with different metadata
    s.upsert(_rec("/x/t1.mp3", "h1b", artist="A", album="Alb", title="T1 remastered", track_no=1))
    albums = s.albums_for_artist(s.iter_artists()[0].id)
    assert len(albums) == 1  # "Alb" survives (t2 still references it)
    titles = sorted(t.title for t in s.tracks_for_album(albums[0].id))
    assert titles == ["T1 remastered", "T2"]  # old "T1" pruned; t2 intact; new title added
