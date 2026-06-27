from pathlib import Path

from music_wiki.cli import main
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def _seed_db(db_path: Path, src_file: Path):
    s = Store.open(str(db_path))
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="Bill Evans", album_title="Waltz", track_title="T", track_no=1,
        disc_no=None, year=1961, label=None, genres=["Jazz"], duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=str(src_file), content_hash="h1", mtime=1.0, fmt="mp3"),
    ))


def test_classify_then_organize_dry_run_then_apply(tmp_path: Path):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"audio")
    db = tmp_path / "wiki.db"
    target = tmp_path / "lib"
    _seed_db(db, src)

    assert main(["classify", "--db", str(db)]) == 0
    # dry-run: nothing copied
    assert main(["organize", "--db", str(db), "--target", str(target)]) == 0
    assert not (target / "재즈").exists()
    # apply: file lands in the genre tree
    assert main(["organize", "--db", str(db), "--target", str(target), "--apply"]) == 0
    assert (target / "재즈" / "Bill Evans" / "Waltz" / "01 - T.mp3").read_bytes() == b"audio"
