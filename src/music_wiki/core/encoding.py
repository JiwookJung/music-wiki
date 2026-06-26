from __future__ import annotations


def _cjk_score(s: str) -> int:
    """Reward Hangul/CJK characters, penalize replacement chars."""
    score = 0
    for ch in s:
        if "가" <= ch <= "힣" or "一" <= ch <= "鿿":
            score += 1
        elif ch == "�":
            score -= 1
    return score


def recover_text(s: str | None) -> str | None:
    if not s:
        return s
    if s.isascii():
        return s
    try:
        candidate = s.encode("latin-1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    if _cjk_score(candidate) <= _cjk_score(s):
        return s
    # Real CP949 mojibake recovers to Korean-dominant text; an accented Latin
    # word (señor, café) would yield a mostly-Latin string — reject those.
    latin_alpha = sum(1 for ch in candidate if ch.isascii() and ch.isalpha())
    return candidate if _cjk_score(candidate) >= latin_alpha else s
