from pathlib import Path
from music_wiki.core.art import find_cover


def test_prefers_cover_named_file(tmp_path: Path):
    (tmp_path / "track.mp3").write_bytes(b"x")
    (tmp_path / "random.jpg").write_bytes(b"x")
    (tmp_path / "cover.jpg").write_bytes(b"x")
    assert find_cover(str(tmp_path)) == str(tmp_path / "cover.jpg")


def test_falls_back_to_sole_image(tmp_path: Path):
    (tmp_path / "art.png").write_bytes(b"x")
    assert find_cover(str(tmp_path)) == str(tmp_path / "art.png")


def test_none_when_no_image(tmp_path: Path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    assert find_cover(str(tmp_path)) is None
