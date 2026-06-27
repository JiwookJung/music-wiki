from pathlib import Path
from music_wiki.cli import main


def test_scan_then_build_wiki(tmp_path: Path, monkeypatch):
    # Build a fake library; stub the tag reader so no real mp3 is needed.
    lib = tmp_path / "lib"
    (lib / "IU" / "Lilac").mkdir(parents=True)
    (lib / "IU" / "Lilac" / "01 Lilac.mp3").write_bytes(b"audio")
    db = tmp_path / "wiki.db"
    out = tmp_path / "vault"

    from music_wiki.core.models import RawTags

    class FakeReader:
        def read(self, path):
            return RawTags(artist="IU", album="Lilac", title="Lilac", track_no=1, year=2021)

    monkeypatch.setattr("music_wiki.cli.MutagenTagReader", lambda: FakeReader())

    assert main(["scan", "--source", str(lib), "--db", str(db)]) == 0
    assert main(["build-wiki", "--db", str(db), "--out", str(out)]) == 0
    assert (out / "albums" / "IU - Lilac.md").exists()
