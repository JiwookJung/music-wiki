from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.enrich import enrich_genres


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


class FakeMB:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def lookup_genres(self, artist, album):
        self.calls.append((artist, album))
        return self.mapping.get(album, [])


def test_enrich_low_confidence_album():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "Astor Piazzolla", "Tango Zero Hour", "x", ["#JUNK"]))
    classify_albums(s)  # junk → 미분류 (0.0)
    mb = FakeMB({"Tango Zero Hour": ["Tango", "Nuevo Tango"]})
    n = enrich_genres(s, mb)
    assert n == 1
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "제3세계" and album.genre_source == "musicbrainz"


def test_enrich_skips_high_confidence_and_manual():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "Bill Evans", "Waltz", "x", ["Jazz"]))   # high conf
    s.upsert(_rec("/b.mp3", "h2", "VA", "Comp", "y", ["#JUNK"]))           # 미분류
    classify_albums(s)
    comp = next(a for ar in s.iter_artists() for a in s.albums_for_artist(ar.id)
                if a.title == "Comp")
    s.set_album_genre(comp.id, "팝", 1.0, "manual")   # human decision
    mb = FakeMB({"Waltz": ["Bebop"], "Comp": ["Latin"]})
    n = enrich_genres(s, mb)
    assert n == 0                                  # high-conf + manual both skipped
    assert ("Bill Evans", "Waltz") not in mb.calls


def test_enrich_no_genres_leaves_unchanged():
    s = _store()
    s.upsert(_rec("/a.mp3", "h1", "X", "Y", "t", ["#JUNK"]))
    classify_albums(s)
    mb = FakeMB({})   # no match
    assert enrich_genres(s, mb) == 0
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "미분류"
