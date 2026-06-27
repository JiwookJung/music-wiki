from music_wiki.organize.buckets import classify_by_rules, BUCKETS, UNCLASSIFIED


def c(genres, artist="x", titles=("y",), album=""):
    return classify_by_rules(list(genres), artist, list(titles), album=album)


def test_clean_single_genre_high_confidence():
    assert c(["Classical"]).bucket == "클래식"
    assert c(["Classical"]).confidence == 0.9
    assert c(["Jazz"]).bucket == "재즈"
    assert c(["Tango"]).bucket == "제3세계"
    assert c(["Soundtrack"]).bucket == "경음악_OST"


def test_classical_guitar_overrides_classical():
    r = c(["Classical Guitar"], artist="Segovia", titles=["Asturias"])
    assert r.bucket == "클래식기타" and r.confidence == 0.9


def test_korean_gating_for_가요():
    # Korean text + ballad keyword → 가요
    assert c(["Ballad"], artist="김광석", titles=["이등병의 편지"]).bucket == "가요"
    # English ballad, no Korean → not 가요 (no other rule) → 미분류
    assert c(["Ballad"], artist="Michael Bolton", titles=["Song"]).bucket == UNCLASSIFIED


def test_blank_genre_korean_low_confidence_가요():
    r = c(["Other"], artist="아이유", titles=["좋은 날"])
    assert r.bucket == "가요" and r.confidence == 0.4


def test_junk_genre_nonkorean_is_unclassified():
    r = c(["#NIPPONSEI @ IRC.RIZON.NET"], artist="x", titles=["y"])
    assert r.bucket == UNCLASSIFIED and r.confidence == 0.0


def test_multi_match_is_low_confidence():
    r = c(["Jazz(Tango,World Fusion)"], artist="x", titles=["y"])
    assert r.confidence == 0.5
    assert r.bucket == "재즈"


def test_buckets_constant():
    assert set(BUCKETS) == {"클래식", "가요", "재즈", "팝", "제3세계", "클래식기타", "경음악_OST"}


def test_substring_keyword_collisions_avoided():
    assert c(["Post-Punk"]).bucket != "경음악_OST"   # "ost" must not fire inside Post
    assert c(["Nostalgia"]).bucket != "경음악_OST"
    assert c(["Platinum"]).bucket != "제3세계"        # "latin" must not fire inside Platinum
    assert c(["OST"]).bucket == "경음악_OST"          # standalone keyword still works
    assert c(["Latin"]).bucket == "제3세계"


def test_album_title_ost_signal():
    # blank/unmatched genre tag + "OST" in the album title → 경음악_OST
    r = c(["Other"], artist="히사이시 조", titles=["테마"], album="벼랑위의 포뇨 OST")
    assert r.bucket == "경음악_OST"
    # "Ghost" must NOT trigger the \bost\b rule
    assert c([], album="Ghost Stories").bucket != "경음악_OST"
    # "soundtrack" anywhere in the title
    assert c([], album="Original Soundtrack").bucket == "경음악_OST"


def test_hiphop_and_rap_map_to_pop():
    assert c(["rap / hip-hop"]).bucket == "팝"   # was 미분류 before (hyphen miss)
    assert c(["Hip-Hop"]).bucket == "팝"
    # "rap" is word-boundary matched: must NOT fire inside "trap"/"rapper"
    assert c(["trap"]).bucket != "팝"
    assert c(["rapper music"]).bucket != "팝"


def test_korean_popular_routes_to_가요():
    # Korean artist + a generic 팝 tag → 가요 (not western 팝)
    assert c(["Pop"], artist="아이유", titles=["좋은 날"]).bucket == "가요"
    assert c(["Hip-Hop"], artist="비와이", titles=["forever"]).bucket == "가요"
    # non-Korean pop stays 팝
    assert c(["Pop"], artist="Dua Lipa", titles=["Levitating"]).bucket == "팝"
