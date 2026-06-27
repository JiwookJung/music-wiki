from pathlib import Path

from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.pages import build_library_pages, render_album_html


def _tracks():
    return [
        {"src": "1-07 - 소녀.mp3", "label": "1-07 소녀", "duration_s": 215.0},
        {"src": "1-08 - A & B.mp3", "label": "1-08 A & B", "duration_s": None},
    ]


def test_render_escapes_and_inlines_audio():
    page = render_album_html(artist="AC/DC", album="Back & Black", year=1980,
                             bucket="팝", description=None, tracks=_tracks())
    assert "<!doctype html>" in page.lower()
    assert "Back &amp; Black" in page          # album text escaped
    assert 'id="player"' in page               # single audio element
    assert "1-08 A &amp; B" in page            # playlist label escaped
    assert "1-08 - A & B.mp3" in page          # raw filename inlined for JS
    assert "encodeURIComponent" in page        # src encoded at click time
    assert "http://" not in page and "https://" not in page   # no network refs


def test_render_includes_description_when_present():
    page = render_album_html(artist="이문세", album="3집", year=1987, bucket="가요",
                             description="잔잔한 발라드.", tracks=_tracks())
    assert "해설" in page and "잔잔한 발라드." in page
    assert "AI 생성" in page


def test_render_omits_description_section_when_absent():
    page = render_album_html(artist="이문세", album="3집", year=1987, bucket="가요",
                             description=None, tracks=_tracks())
    assert "해설" not in page


def test_render_zero_duration_is_shown_not_dropped():
    page = render_album_html(
        artist="A", album="B", year=None, bucket=None, description=None,
        tracks=[{"src": "x.mp3", "label": "01 x", "duration_s": 0.0}],
    )
    assert "0:00" in page          # 0.0 is a real duration, not "missing"


def test_render_none_duration_omits_dur_span():
    page = render_album_html(
        artist="A", album="B", year=None, bucket=None, description=None,
        tracks=[{"src": "x.mp3", "label": "01 x", "duration_s": None}],
    )
    assert 'class="dur"' not in page


def _rec(path, hash_, title="소녀", track_no=7):
    return TrackRecord(
        artist_name="이문세", album_title="3집", track_title=title, track_no=track_no,
        disc_no=1, year=1987, label=None, genres=["Ballad"], duration_s=215.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _seed_two_track_album(tmp_path: Path) -> tuple[Store, Path]:
    folder = tmp_path / "가요" / "이문세" / "3집"
    folder.mkdir(parents=True)
    (folder / "1-07 - 소녀.mp3").write_bytes(b"a")
    (folder / "1-08 - 그늘.mp3").write_bytes(b"b")
    s = Store.open(":memory:")
    s.init_schema()
    s.upsert(_rec("/src/7.mp3", "h1", title="소녀", track_no=7))
    s.upsert(_rec("/src/8.mp3", "h2", title="그늘", track_no=8))
    s.set_organized_path("/src/7.mp3", str(folder / "1-07 - 소녀.mp3"))
    s.set_organized_path("/src/8.mp3", str(folder / "1-08 - 그늘.mp3"))
    return s, folder


def test_build_pages_writes_one_index_per_album(tmp_path):
    s, folder = _seed_two_track_album(tmp_path)
    assert build_library_pages(s) == 1
    page = (folder / "index.html").read_text(encoding="utf-8")
    assert "이문세 — 3집" in page
    assert "소녀" in page and "그늘" in page


def test_build_pages_dry_run_writes_nothing(tmp_path):
    s, folder = _seed_two_track_album(tmp_path)
    assert build_library_pages(s, dry_run=True) == 1
    assert not (folder / "index.html").exists()


def test_build_pages_skips_folder_not_on_disk(tmp_path):
    s = Store.open(":memory:")
    s.init_schema()
    s.upsert(_rec("/src/7.mp3", "h1"))
    s.set_organized_path("/src/7.mp3", "/nope/가요/이문세/3집/1-07 - 소녀.mp3")
    assert build_library_pages(s) == 0


def test_build_pages_idempotent(tmp_path):
    s, folder = _seed_two_track_album(tmp_path)
    build_library_pages(s)
    first = (folder / "index.html").read_text(encoding="utf-8")
    assert build_library_pages(s) == 1
    assert (folder / "index.html").read_text(encoding="utf-8") == first
