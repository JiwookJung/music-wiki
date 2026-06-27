from music_wiki.core.models import RawTags, SourceFile, TrackRecord


def test_rawtags_defaults_to_none():
    t = RawTags()
    assert t.artist is None and t.duration_s is None


def test_trackrecord_holds_source_and_genres():
    src = SourceFile(abs_path="/x/a.mp3", content_hash="h", mtime=1.0, fmt="mp3")
    rec = TrackRecord(
        artist_name="IU", album_title="Lilac", track_title="Lilac",
        track_no=1, disc_no=None, year=2021, label=None, genres=["K-Pop"],
        duration_s=180.0, cover_path=None, source=src,
    )
    assert rec.source.fmt == "mp3"
    assert rec.genres == ["K-Pop"]
    assert src.decode_status == "ok" and src.is_drm is False


def test_trackrecord_genres_not_shared():
    src = SourceFile(abs_path="/x/a.mp3", content_hash="h", mtime=1.0, fmt="mp3")
    a = TrackRecord(
        artist_name="A", album_title="X", track_title="T",
        track_no=None, disc_no=None, year=None, label=None, source=src,
    )
    b = TrackRecord(
        artist_name="B", album_title="Y", track_title="U",
        track_no=None, disc_no=None, year=None, label=None, source=src,
    )
    a.genres.append("Rock")
    assert a.genres == ["Rock"]
    assert b.genres == []
    assert a.genres is not b.genres
