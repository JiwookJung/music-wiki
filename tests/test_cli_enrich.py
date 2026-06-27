from pathlib import Path

from music_wiki.cli import main
from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.store import Store


def test_classify_enrich_genre(tmp_path: Path, monkeypatch):
    db = tmp_path / "wiki.db"
    s = Store.open(str(db))
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="Astor Piazzolla", album_title="Tango Zero Hour", track_title="t",
        track_no=1, disc_no=None, year=1986, label=None, genres=["#JUNK"],
        duration_s=60.0, cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    ))

    class FakeMB:
        def lookup_genres(self, artist, album):
            return ["Tango"] if album == "Tango Zero Hour" else []

    monkeypatch.setattr("music_wiki.cli.HttpMusicBrainzClient", lambda *a, **k: FakeMB())

    assert main(["classify", "--db", str(db), "--enrich-genre"]) == 0
    album = s.albums_for_artist(s.iter_artists()[0].id)[0]
    assert album.genre_bucket == "제3세계" and album.genre_source == "musicbrainz"
