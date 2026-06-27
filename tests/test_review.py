from pathlib import Path

from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store
from music_wiki.organize.classify import classify_albums
from music_wiki.organize.review import export_review, import_review


def _rec(path, hash_, artist, album, title, genres):
    return TrackRecord(
        artist_name=artist, album_title=album, track_title=title, track_no=1,
        disc_no=None, year=2000, label=None, genres=genres, duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=path, content_hash=hash_, mtime=1.0, fmt="mp3"),
    )


def _seeded():
    s = Store.open(":memory:")
    s.init_schema()
    s.upsert(_rec("/a.mp3", "h1", "Bill Evans", "Waltz", "x", ["Jazz"]))       # high conf
    s.upsert(_rec("/b.mp3", "h2", "VA", "Comp", "y", ["#IRC JUNK"]))           # 미분류
    classify_albums(s)
    return s


def test_export_only_low_confidence(tmp_path: Path):
    s = _seeded()
    out = tmp_path / "review.csv"
    n = export_review(s, str(out), threshold=0.8)
    text = out.read_text(encoding="utf-8")
    assert n == 1                       # only the 미분류 album
    assert "Comp" in text and "Waltz" not in text
    assert "signals" in text            # header present


def test_import_applies_manual_buckets(tmp_path: Path):
    s = _seeded()
    out = tmp_path / "review.csv"
    export_review(s, str(out), threshold=0.8)
    # user edits the proposed_bucket to a real bucket
    rows = out.read_text(encoding="utf-8").replace("미분류", "제3세계")
    out.write_text(rows, encoding="utf-8")
    applied = import_review(s, str(out))
    assert applied == 1
    comp = next(a for ar in s.iter_artists() for a in s.albums_for_artist(ar.id)
                if a.title == "Comp")
    assert comp.genre_bucket == "제3세계" and comp.genre_source == "manual"


def test_import_skips_invalid_bucket(tmp_path: Path):
    s = _seeded()
    out = tmp_path / "review.csv"
    export_review(s, str(out), threshold=0.8)
    out.write_text(out.read_text(encoding="utf-8").replace("미분류", "NOTABUCKET"),
                   encoding="utf-8")
    assert import_review(s, str(out)) == 0


def test_import_skips_malformed_album_id(tmp_path):
    s = _seeded()
    out = tmp_path / "review.csv"
    export_review(s, str(out), threshold=0.8)
    text = out.read_text(encoding="utf-8").replace("미분류", "제3세계")
    text += "notanumber,X,Y,재즈,0.10,rule,\n"   # junk row, invalid album_id
    out.write_text(text, encoding="utf-8")
    assert import_review(s, str(out)) == 1   # valid row applied, junk row skipped


def test_export_skips_manual_even_if_low_conf(tmp_path):
    s = _seeded()
    comp = next(a for ar in s.iter_artists() for a in s.albums_for_artist(ar.id)
                if a.title == "Comp")
    s.set_album_genre(comp.id, "제3세계", 1.0, "manual")
    out = tmp_path / "review.csv"
    assert export_review(s, str(out), threshold=0.8) == 0   # nothing left to review
