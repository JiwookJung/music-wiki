from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.classify import classify_albums


def _rec(path, hash_, artist, album, title, genres):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=1,
        disc_no=None, year=2000, label=None, genres=genres, duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_classify_writes_buckets():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "Bill Evans", "Waltz for Debby", "My Foolish Heart", ["Jazz"]))
    s.upsert(_rec("/b.mp3", "h2", "김광석", "다시부르기", "이등병의 편지", ["Ballad"]))
    n = classify_albums(s)
    assert n == 2
    by_artist = {a.name: s.albums_for_artist(a.id)[0] for a in s.iter_artists()}
    assert by_artist["Bill Evans"].genre_bucket == "재즈"
    assert by_artist["김광석"].genre_bucket == "가요"
    assert by_artist["Bill Evans"].genre_source == "rule"


def test_classify_skips_manual():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "Bill Evans", "Waltz", "x", ["Jazz"]))
    album_id = s.albums_for_artist(s.iter_artists()[0].id)[0].id
    s.set_album_genre(album_id, "팝", 1.0, "manual")
    classify_albums(s)
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "팝" and album.genre_source == "manual"
