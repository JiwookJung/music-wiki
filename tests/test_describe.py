from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.describe import DESCRIBE_SYSTEM, describe_albums


class FakeLLM:
    model = "qwen3-14b"

    def __init__(self, content="  잔잔한 발라드 명반.  "):
        self.content = content
        self.calls = 0
        self.last_user = None

    def complete(self, system, user, *, json_schema=None):
        self.calls += 1
        self.last_user = user
        return self.content


def _rec(path, hash_, artist="이문세", album="3집", title="소녀", genres=None):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=1,
        disc_no=None, year=1987, label=None,
        genres=genres if genres is not None else ["Ballad"], duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_describe_writes_stripped_text_and_source():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    llm = FakeLLM()
    n = describe_albums(s, llm)
    assert n == 1
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description == "잔잔한 발라드 명반."          # stripped
    assert album.description_source == "llm:qwen3-14b"


def test_describe_is_idempotent_unless_force():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    llm = FakeLLM()
    assert describe_albums(s, llm) == 1
    assert describe_albums(s, llm) == 0          # already has description → skip
    assert llm.calls == 1
    assert describe_albums(s, llm, force=True) == 1   # force regenerates
    assert llm.calls == 2


def test_describe_limit_caps_calls():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1", artist="A", album="Al1"))
    s.upsert(_rec("/x/2.mp3", "h2", artist="A", album="Al2"))
    llm = FakeLLM()
    n = describe_albums(s, llm, limit=1)
    assert n == 1 and llm.calls == 1


def test_describe_skips_empty_response():
    s = _store()
    s.upsert(_rec("/x/1.mp3", "h1"))
    llm = FakeLLM(content="   ")
    n = describe_albums(s, llm)
    assert n == 0
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.description is None


def test_describe_system_prompt_forbids_fabrication():
    assert "단정하지 않는다" in DESCRIBE_SYSTEM
