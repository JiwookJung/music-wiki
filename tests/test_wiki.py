from pathlib import Path
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.core.wiki import WikiGenerator, safe_filename


def _seed(store):
    store.upsert(TrackRecord(
        artist_name="IU", album_title="Lilac", track_title="Lilac",
        track_no=1, disc_no=None, year=2021, label="EDAM", genres=["K-Pop"],
        duration_s=215.0, cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    ))


def test_safe_filename_strips_separators():
    assert safe_filename("AC/DC: Live") == "AC_DC_ Live"


def test_generate_writes_artist_and_album_pages(tmp_path: Path):
    s = Store.open(":memory:")
    s.init_schema()
    _seed(s)
    WikiGenerator(s).generate(str(tmp_path))
    artist_md = (tmp_path / "artists" / "IU.md").read_text(encoding="utf-8")
    assert "[[IU - Lilac]]" in artist_md
    album_md = (tmp_path / "albums" / "IU - Lilac.md").read_text(encoding="utf-8")
    assert "[[IU]]" in album_md
    assert "디지털 보유" in album_md
    assert "Lilac" in album_md and "2021" in album_md


def test_wiki_links_resolve_for_special_char_names(tmp_path):
    s = Store.open(":memory:")
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="AC/DC", album_title="Live: At Wembley", track_title="T",
        track_no=1, disc_no=None, year=1992, label=None, genres=[],
        duration_s=None, cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="hx", mtime=1.0, fmt="mp3"),
    ))
    WikiGenerator(s).generate(str(tmp_path))
    artist_md = (tmp_path / "artists" / "AC_DC.md").read_text(encoding="utf-8")
    assert "[[AC_DC - Live_ At Wembley]]" in artist_md
    album_md = (tmp_path / "albums" / "AC_DC - Live_ At Wembley.md").read_text(encoding="utf-8")
    assert "[[AC_DC]]" in album_md


def test_generate_writes_drm_page(tmp_path):
    s = Store.open(":memory:")
    s.init_schema()
    s.record_drm(SourceFile(abs_path="/lib/locked.enc", content_hash="d1",
                            mtime=1.0, fmt="enc", is_drm=True))
    WikiGenerator(s).generate(str(tmp_path))
    drm_md = (tmp_path / "DRM.md").read_text(encoding="utf-8")
    assert "재생불가" in drm_md and "/lib/locked.enc" in drm_md
