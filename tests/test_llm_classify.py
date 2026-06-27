from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.llm_classify import classify_low_confidence_llm


class FakeLLM:
    model = "fake"

    def __init__(self, content):
        self.content = content
        self.calls = 0

    def complete(self, system, user, *, json_schema=None):
        self.calls += 1
        return self.content


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


def test_llm_updates_low_confidence_album():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", "미상가수", "미상앨범", "곡", ["#JUNK"]))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "미분류", 0.0, "rule")
    llm = FakeLLM('{"bucket": "재즈", "confidence": 0.9, "reasoning": "스윙 편성"}')
    n = classify_low_confidence_llm(s, llm)
    assert n == 1
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "재즈"
    assert album.genre_source == "llm"
    assert album.genre_confidence == 0.9


def test_llm_skips_manual_and_high_confidence():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", "A", "Manual", "t", ["x"]))
    s.upsert(_rec("/x/2.mp3", "h2", "A", "HighConf", "t", ["jazz"]))
    albums = {a.title: a for a in s.albums_for_artist(s.iter_artists()[0].id)}
    s.set_album_genre(albums["Manual"].id, "가요", 1.0, "manual")
    s.set_album_genre(albums["HighConf"].id, "재즈", 0.9, "rule")
    llm = FakeLLM('{"bucket": "팝", "confidence": 0.95, "reasoning": "x"}')
    n = classify_low_confidence_llm(s, llm)
    assert n == 0
    assert llm.calls == 0   # nothing eligible → no LLM call


def test_llm_parse_failure_is_isolated():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", "A", "Alb", "t", ["#JUNK"]))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "미분류", 0.0, "rule")
    llm = FakeLLM("not json at all")
    n = classify_low_confidence_llm(s, llm)   # must not raise
    assert n == 0
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "미분류"   # unchanged


def test_llm_ignores_bucket_not_in_taxonomy():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", "A", "Alb", "t", ["#JUNK"]))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "미분류", 0.0, "rule")
    llm = FakeLLM('{"bucket": "Heavy Metal", "confidence": 0.9, "reasoning": "x"}')
    n = classify_low_confidence_llm(s, llm)
    assert n == 0   # bucket outside the 7 buckets → ignored
