from music_wiki.organize.buckets import classify_by_rules, BUCKETS, UNCLASSIFIED


def c(genres, artist="x", titles=("y",)):
    return classify_by_rules(list(genres), artist, list(titles))


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
    assert r.bucket in ("재즈", "제3세계")


def test_buckets_constant():
    assert set(BUCKETS) == {"클래식", "가요", "재즈", "팝", "제3세계", "클래식기타", "경음악_OST"}
