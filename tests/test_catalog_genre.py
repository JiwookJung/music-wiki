"""catalog 의 장르 통일: 디지털·실물이 같은 장르를 다른 이름으로 부르는 문제.

정본은 실물(엑셀) 쪽 이름 — 분류코드 문자와 묶여 있어 라벨에 인쇄된 코드와
어긋나면 안 되기 때문. 통일은 파생 테이블에서만 하고 music-wiki.db 의
genre_bucket 은 건드리지 않는다(분류·해설·md 파이프라인이 의존).
"""
import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mw_build_catalog",
    Path(__file__).resolve().parents[1] / "scripts" / "build_catalog.py")
build_catalog = importlib.util.module_from_spec(_SPEC)
sys.modules["mw_build_catalog"] = build_catalog
_SPEC.loader.exec_module(build_catalog)

canon = build_catalog.canon_genre


def test_digital_aliases_fold_into_physical_names():
    """홈 화면에 같은 장르가 두 버킷으로 갈라지던 원인."""
    assert canon("경음악_OST") == "OST·경음악"
    assert canon("제3세계") == "월드"


def test_physical_names_pass_through():
    """분류코드 문자(GENRE_LETTER)를 가진 이름은 그대로 정본."""
    for g in ("클래식", "클래식기타", "재즈", "탱고", "월드", "팝", "가요", "OST·경음악"):
        assert canon(g) == g


def test_missing_genre_becomes_unclassified():
    assert canon(None) == "미분류"
    assert canon("") == "미분류"
    assert canon("미분류") == "미분류"


def test_unknown_genre_is_left_alone():
    """모르는 이름을 임의로 뭉개지 않는다 — 새 장르가 조용히 사라지면 안 된다."""
    assert canon("노이즈") == "노이즈"


def test_canon_map_only_covers_digital_bucket_vocabulary():
    """매핑 출발점은 전부 디지털 버킷 이름이어야 한다(반대 방향 매핑 방지)."""
    from music_wiki.organize.buckets import BUCKETS
    assert set(build_catalog.GENRE_CANON) <= set(BUCKETS)
