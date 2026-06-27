from music_wiki.core.tags import MutagenTagReader, extract_tags


class _FakeInfo:
    length = 200.0


class _FakeFile(dict):
    """Mimics a mutagen easy File: dict of list-values + .info.length."""
    info = _FakeInfo()


def _mojibake(korean: str) -> str:
    return korean.encode("cp949").decode("latin-1")


def test_extract_reads_and_recovers():
    mf = _FakeFile({
        "artist": [_mojibake("아이유")],
        "album": ["Lilac"],
        "title": [_mojibake("좋은 날")],
        "tracknumber": ["3/12"],
        "date": ["2021"],
        "genre": ["K-Pop"],
    })
    t = extract_tags(mf)
    assert t.artist == "아이유"
    assert t.album == "Lilac"
    assert t.title == "좋은 날"
    assert t.track_no == 3
    assert t.year == 2021
    assert t.duration_s == 200.0


def test_reader_returns_empty_on_unreadable():
    reader = MutagenTagReader(loader=lambda p: None)
    assert extract_tags is not None  # sanity
    t = reader.read("/nope.mp3")
    assert t.artist is None and t.album is None
