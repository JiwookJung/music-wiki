from pathlib import Path
from music_wiki.core.models import RawTags
from music_wiki.core.store import Store
from music_wiki.ingest.audio.scan import scan_library, file_signature


class FakeReader:
    """Returns tags based on filename so tests need no real mp3."""
    def read(self, path: str) -> RawTags:
        if "iu" in path.lower():
            return RawTags(artist="IU", album="Lilac", title="Lilac", track_no=1, year=2021)
        return RawTags()


def _store():
    s = Store.open(":memory:")
    s.init_schema()
    return s


def test_ingests_audio_and_records_drm(tmp_path: Path):
    (tmp_path / "iu.mp3").write_bytes(b"audio")
    (tmp_path / "locked.enc").write_bytes(b"drm")
    (tmp_path / "notes.txt").write_bytes(b"ignore")
    s = _store()
    stats = scan_library(str(tmp_path), s, FakeReader())
    assert stats.ingested == 1
    assert stats.drm == 1
    assert s.iter_artists()[0].name == "IU"
    assert s.drm_count() == 1


def test_rerun_skips_unchanged(tmp_path: Path):
    (tmp_path / "iu.mp3").write_bytes(b"audio")
    s = _store()
    scan_library(str(tmp_path), s, FakeReader())
    stats2 = scan_library(str(tmp_path), s, FakeReader())
    assert stats2.skipped == 1 and stats2.ingested == 0


def test_signature_is_content_addressed(tmp_path):
    import os
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    h1, mtime, size = file_signature(str(f))
    assert len(h1) == 40 and all(c in "0123456789abcdef" for c in h1)
    # stable for the same (path, size, mtime)
    os.utime(f, (mtime, mtime))
    assert file_signature(str(f))[0] == h1
    # size participates in the hash: different size, same mtime → different hash
    f.write_bytes(b"xxxxxxxx")
    os.utime(f, (mtime, mtime))
    assert file_signature(str(f))[0] != h1


def test_ingests_case_insensitive_extension(tmp_path):
    (tmp_path / "IU.MP3").write_bytes(b"audio")
    s = _store()
    stats = scan_library(str(tmp_path), s, FakeReader())
    assert stats.ingested == 1


def test_skip_unchanged_false_bypasses_skip_gate(tmp_path):
    (tmp_path / "iu.mp3").write_bytes(b"audio")
    s = _store()
    scan_library(str(tmp_path), s, FakeReader())
    stats2 = scan_library(str(tmp_path), s, FakeReader(), skip_unchanged=False)
    assert stats2.skipped == 0 and stats2.ingested == 1
