"""OKF v0.2 적합성: 모든 생성 md는 YAML frontmatter + 비어있지 않은 type 필수."""
import json
from pathlib import Path

from music_wiki.core.models import SourceFile, TrackRecord
from music_wiki.core.physical_wiki import generate_physical_wiki, write_home_index
from music_wiki.core.store import Store
from music_wiki.core.wiki import WikiGenerator


def _okf_ok(md: str) -> bool:
    if not md.startswith("---\n"):
        return False
    body = md.split("---\n", 2)
    return len(body) >= 3 and "type:" in body[1]


def test_all_generated_md_have_okf_frontmatter(tmp_path: Path):
    s = Store.open(":memory:")
    s.init_schema()
    s.upsert(TrackRecord(
        artist_name="IU", album_title="Lilac", track_title="Lilac", track_no=1,
        disc_no=None, year=2021, label=None, genres=["Ballad"], duration_s=180.0,
        cover_path=None,
        source=SourceFile(abs_path="/x/1.mp3", content_hash="h1", mtime=1.0, fmt="mp3"),
    ))
    WikiGenerator(s).generate(str(tmp_path))
    pj = tmp_path / "p.json"
    pj.write_text(json.dumps([{"code": "K-ㅇ01-01", "genre": "가요", "artist": "이문세",
                               "album": "3집", "rep": "", "composer": "", "performer": "",
                               "desc": "", "discogs_id": "", "db_url": "", "label_cat": "",
                               "media": ["LP"], "locations": ["LP좌측선반1층"], "copies": 1,
                               "digital": False}], ensure_ascii=False), encoding="utf-8")
    generate_physical_wiki(str(tmp_path), str(pj))
    write_home_index(str(tmp_path), {"가요": 1}, str(pj))
    mds = list(tmp_path.rglob("*.md"))
    assert len(mds) >= 5
    bad = [p.name for p in mds if not _okf_ok(p.read_text(encoding="utf-8"))]
    assert not bad, f"OKF 위반: {bad}"


def test_physical_album_frontmatter_fields(tmp_path: Path):
    pj = tmp_path / "p.json"
    pj.write_text(json.dumps([{"code": "J-B01-02", "genre": "재즈", "artist": "Bill Evans",
                               "album": "Waltz", "rep": "", "composer": "", "performer": "",
                               "desc": "명연이다.", "discogs_id": "", "db_url": "",
                               "label_cat": "", "media": ["LP"], "locations": ["LP침대옆"],
                               "copies": 1, "digital": True}], ensure_ascii=False),
                  encoding="utf-8")
    generate_physical_wiki(str(tmp_path), str(pj))
    md = (tmp_path / "albums" / "Bill Evans - Waltz.md").read_text(encoding="utf-8")
    fm = md.split("---\n")[1]
    assert 'type: "Album"' in fm
    assert 'code: "J-B01-02"' in fm
    assert "generated:" in fm and "status: stable" in fm
