from music_wiki.organize.pages import render_album_html


def _tracks():
    return [
        {"src": "1-07 - 소녀.mp3", "label": "1-07 소녀", "duration_s": 215.0},
        {"src": "1-08 - A & B.mp3", "label": "1-08 A & B", "duration_s": None},
    ]


def test_render_escapes_and_inlines_audio():
    page = render_album_html(artist="AC/DC", album="Back & Black", year=1980,
                             bucket="팝", description=None, tracks=_tracks())
    assert "<!doctype html>" in page.lower()
    assert "Back &amp; Black" in page          # album text escaped
    assert 'id="player"' in page               # single audio element
    assert "1-08 A &amp; B" in page            # playlist label escaped
    assert "1-08 - A & B.mp3" in page          # raw filename inlined for JS
    assert "encodeURIComponent" in page        # src encoded at click time
    assert "http://" not in page and "https://" not in page   # no network refs


def test_render_includes_description_when_present():
    page = render_album_html(artist="이문세", album="3집", year=1987, bucket="가요",
                             description="잔잔한 발라드.", tracks=_tracks())
    assert "해설" in page and "잔잔한 발라드." in page
    assert "AI 생성" in page


def test_render_omits_description_section_when_absent():
    page = render_album_html(artist="이문세", album="3집", year=1987, bucket="가요",
                             description=None, tracks=_tracks())
    assert "해설" not in page
