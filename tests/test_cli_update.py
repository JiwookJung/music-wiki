from pathlib import Path

from music_wiki.cli import main
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def test_update_generates_wiki_home_and_todo(tmp_path: Path):
    src = tmp_path / "lib"
    src.mkdir()
    db = tmp_path / "w.db"
    out = tmp_path / "vault"
    s = Store.open(str(db))
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="Bill Evans", album_title="Waltz", track_title="T", track_no=1,
        disc_no=None, year=1961, label=None, genres=["Jazz"], duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=str(src / "a.mp3"), content_hash="h1",
                          mtime=1.0, fmt="mp3"),
    ))
    assert main(["update", "--db", str(db), "--source", str(src),
                 "--out", str(out), "--no-physical"]) == 0
    # 위키 + 홈 + 해설필요 목록 생성
    assert (out / "albums" / "Bill Evans - Waltz.md").exists()
    home = (out / "홈.md").read_text(encoding="utf-8")
    assert "재즈" in home                      # 신규 앨범이 규칙 분류됨
    todo = (out / "작업목록-해설필요.md").read_text(encoding="utf-8")
    assert "Bill Evans — Waltz" in todo


def test_update_preserves_existing_classification(tmp_path: Path):
    src = tmp_path / "lib"
    src.mkdir()
    db = tmp_path / "w.db"
    s = Store.open(str(db))
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="A", album_title="B", track_title="T", track_no=1,
        disc_no=None, year=2000, label=None, genres=["#junk"], duration_s=60.0,
        cover_path=None,
        source=SourceFile(abs_path=str(src / "a.mp3"), content_hash="h1",
                          mtime=1.0, fmt="mp3"),
    ))
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    s.set_album_genre(album.id, "재즈", 0.85, "claude")   # 기존 claude 분류
    main(["update", "--db", str(db), "--source", str(src),
          "--out", str(tmp_path / "v"), "--no-physical"])
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "재즈" and album.genre_source == "claude"  # 보존
