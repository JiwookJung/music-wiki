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
    return candidate if _cjk_score(candidate) > _cjk_score(s) else s
