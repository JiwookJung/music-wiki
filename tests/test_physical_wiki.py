import json

from music_wiki.core.physical_wiki import generate_physical_wiki, write_home_index


def _data():
    return [
        {"code": "J-B01-02", "genre": "재즈", "artist": "Bill Evans Trio",
         "album": "Waltz for Debby", "rep": "My Foolish Heart, Waltz for Debby",
         "composer": "", "performer": "", "desc": "재즈 트리오의 명연.",
         "discogs_id": "123", "db_url": "https://www.discogs.com/release/123",
         "label_cat": "Riverside", "media": ["LP"], "locations": ["LP중앙선반2열2층"],
         "copies": 1, "digital": True},
        {"code": "C-B0-G01-01", "genre": "클래식", "artist": "Bach - Glenn Gould",
         "album": "The Goldberg Variations", "rep": "골드베르크 변주곡",
         "composer": "Bach", "performer": "Glenn Gould", "desc": "",
         "discogs_id": "", "db_url": "", "label_cat": "CBS", "media": ["LP"],
         "locations": ["LP좌측선반2층"], "copies": 2, "digital": False},
    ]


def test_physical_album_md_created_with_code_and_youtube(tmp_path):
    pj = tmp_path / "phys.json"
    pj.write_text(json.dumps(_data(), ensure_ascii=False), encoding="utf-8")
    stats = generate_physical_wiki(str(tmp_path), str(pj))
    assert stats["albums_created"] == 2
    md = (tmp_path / "albums" / "Bill Evans Trio - Waltz for Debby.md").read_text(encoding="utf-8")
    assert "분류코드: **J-B01-02**" in md
    assert "youtube.com/results" in md          # 검색 링크
    assert "## 해설" in md and "재즈 트리오" in md
    assert "💿 디지털 보유" in md


def test_digital_album_md_is_preserved(tmp_path):
    (tmp_path / "albums").mkdir()
    existing = tmp_path / "albums" / "Bill Evans Trio - Waltz for Debby.md"
    existing.write_text("# Waltz for Debby\n(디지털 위키 페이지)\n", encoding="utf-8")
    pj = tmp_path / "phys.json"
    pj.write_text(json.dumps(_data(), ensure_ascii=False), encoding="utf-8")
    stats = generate_physical_wiki(str(tmp_path), str(pj))
    assert stats["skipped_existing"] == 1
    assert "(디지털 위키 페이지)" in existing.read_text(encoding="utf-8")  # untouched


def test_artist_section_appended_idempotently(tmp_path):
    (tmp_path / "artists").mkdir()
    ap = tmp_path / "artists" / "Bill Evans Trio.md"
    ap.write_text("# Bill Evans Trio\n\n## 앨범\n- [[x]]\n", encoding="utf-8")
    pj = tmp_path / "phys.json"
    pj.write_text(json.dumps(_data(), ensure_ascii=False), encoding="utf-8")
    generate_physical_wiki(str(tmp_path), str(pj))
    generate_physical_wiki(str(tmp_path), str(pj))   # 재실행
    txt = ap.read_text(encoding="utf-8")
    assert txt.count("## 실물 음반") == 1            # 중복 append 없음
    assert "`J-B01-02`" in txt and "## 앨범" in txt  # 기존 디지털 섹션 보존


def test_home_index(tmp_path):
    pj = tmp_path / "phys.json"
    pj.write_text(json.dumps(_data(), ensure_ascii=False), encoding="utf-8")
    write_home_index(str(tmp_path), {"재즈": 3, "가요": 5}, str(pj))
    home = (tmp_path / "홈.md").read_text(encoding="utf-8")
    assert "디지털 앨범 **8**" in home
    assert "재즈: 3개" in home and "실물 정리장 지도" in home
