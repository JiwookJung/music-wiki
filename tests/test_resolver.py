from music_wiki.core.models import RawTags, SourceFile
from music_wiki.core.resolver import EntityResolver

SRC = SourceFile(abs_path="/x.mp3", content_hash="h", mtime=1.0, fmt="mp3")


def test_tag_first():
    tags = RawTags(artist="IU", album="Lilac", title="Lilac (feat. SUGA)", track_no=1)
    rec = EntityResolver().resolve(tags, "/lib/whatever.mp3", SRC)
    assert rec.artist_name == "IU"
    assert rec.album_title == "Lilac"
    assert rec.track_title == "Lilac"  # feat. stripped


def test_folder_fallback_when_tags_missing():
    tags = RawTags()
    path = "/mnt/win/memory/음악/Music/김동률/감사/02 출발.mp3"
    rec = EntityResolver().resolve(tags, path, SRC)
    assert rec.artist_name == "김동률"
    assert rec.album_title == "감사"
    assert rec.track_title == "출발"
    assert rec.track_no == 2


def test_melon_flat_pattern():
    tags = RawTags()
    path = "/mnt/win/memory/음악/melon/아이유-01-좋은 날.mp3"
    rec = EntityResolver().resolve(tags, path, SRC)
    assert rec.artist_name == "아이유"
    assert rec.track_title == "좋은 날"
    assert rec.track_no == 1
