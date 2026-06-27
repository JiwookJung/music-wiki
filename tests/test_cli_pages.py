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
        source=SourceFile(abs_path=str(src_file), content_hash="h1", mtime=1.0,
                          fmt="mp3"),
    ))


def test_organize_apply_generates_album_page(tmp_path: Path):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"audio")
    db = tmp_path / "wiki.db"
    target = tmp_path / "lib"
    _seed_db(db, src)

    assert main(["classify", "--db", str(db)]) == 0
    assert main(["organize", "--db", str(db), "--target", str(target),
                 "--apply"]) == 0
    page = target / "재즈" / "Bill Evans" / "Waltz" / "index.html"
    assert page.exists()
    assert "Bill Evans — Waltz" in page.read_text(encoding="utf-8")


def test_build_pages_command_rerenders(tmp_path: Path):
    src = tmp_path / "song.mp3"
    src.write_bytes(b"audio")
    db = tmp_path / "wiki.db"
    target = tmp_path / "lib"
    _seed_db(db, src)
    main(["classify", "--db", str(db)])
    main(["organize", "--db", str(db), "--target", str(target), "--apply"])
    page = target / "재즈" / "Bill Evans" / "Waltz" / "index.html"
    page.unlink()  # remove, then rebuild via standalone command
    assert main(["build-pages", "--db", str(db)]) == 0
    assert page.exists()
