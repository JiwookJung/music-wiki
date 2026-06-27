from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.plan import build_plan


def _rec(path, hash_, artist, album, title, track_no, genres, disc_no=None):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=track_no,
        disc_no=disc_no, year=2000, label=None, genres=genres, duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_plan_path_layout():
    s = _store()
    s.upsert(_rec("/src/a.mp3", "h1", "Bill Evans", "Waltz for Debby",
                  "My Foolish Heart", 1, ["Jazz"]))
    classify_albums(s)
    ops = build_plan(s, "/home/lib")
    assert len(ops) == 1
    assert ops[0].src == "/src/a.mp3"
    assert ops[0].dst == "/home/lib/재즈/Bill Evans/Waltz for Debby/01 - My Foolish Heart.mp3"


def test_plan_disc_prefix_and_unclassified():
    s = _store()
    s.upsert(_rec("/src/b.mp3", "h2", "VA", "Comp", "Track", 3, ["#JUNK"], disc_no=2))
    classify_albums(s)  # junk → 미분류
    dst = build_plan(s, "/home/lib")[0].dst
    assert dst == "/home/lib/미분류/VA/Comp/2-03 - Track.mp3"


def test_plan_sanitizes_special_chars():
    s = _store()
    s.upsert(_rec("/src/c.mp3", "h3", "AC/DC", "Live: At X", "T:1", 1, ["Rock"]))
    classify_albums(s)
    dst = build_plan(s, "/home/lib")[0].dst
    assert dst == "/home/lib/팝/AC_DC/Live_ At X/01 - T_1.mp3"


def test_plan_dedups_same_track_multiple_sources():
    s = _store()
    s.upsert(_rec("/src/1.mp3", "h1", "IU", "Lilac", "Lilac", 1, ["Ballad"]))
    s.upsert(_rec("/src/2.mp3", "h2", "IU", "Lilac", "Lilac", 1, ["Ballad"]))
    classify_albums(s)
    ops = build_plan(s, "/home/lib")
    assert len(ops) == 1  # one target path → one copy


def test_plan_suffixes_distinct_tracks_colliding_on_sanitized_path():
    s = _store()
    # two DIFFERENT tracks (distinct title_key), same album+track_no, whose titles
    # sanitize to the same filename → both must be copied (suffix, not dropped)
    s.upsert(_rec("/src/1.mp3", "h1", "A", "Alb", "Song?", 1, ["Jazz"]))
    s.upsert(_rec("/src/2.mp3", "h2", "A", "Alb", "Song*", 1, ["Jazz"]))
    classify_albums(s)
    ops = build_plan(s, "/home/lib")
    assert len(ops) == 2
    assert {o.src for o in ops} == {"/src/1.mp3", "/src/2.mp3"}
    assert {o.dst for o in ops} == {
        "/home/lib/재즈/A/Alb/01 - Song_.mp3",
        "/home/lib/재즈/A/Alb/01 - Song_ (2).mp3",
    }
