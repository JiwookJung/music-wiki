from music_wiki.core.encoding import recover_text


def _mojibake(korean: str) -> str:
    # Simulate cp949 bytes mis-decoded as latin-1 (the exact mutagen failure mode).
    return korean.encode("cp949").decode("latin-1")


def test_recovers_korean_mojibake():
    assert recover_text(_mojibake("아이유")) == "아이유"
    assert recover_text(_mojibake("좋은 날")) == "좋은 날"


def test_leaves_ascii_untouched():
    assert recover_text("Lilac") == "Lilac"


def test_leaves_clean_korean_untouched():
    assert recover_text("아이유") == "아이유"


def test_handles_none_and_empty():
    assert recover_text(None) is None
    assert recover_text("") == ""


def test_leaves_accented_latin_untouched():
    assert recover_text("señor") == "señor"
    assert recover_text("café") == "café"
    assert recover_text("Antonín Dvořák") == "Antonín Dvořák"
