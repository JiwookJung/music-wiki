from __future__ import annotations

import re
from dataclasses import dataclass

from music_wiki.core.encoding import recover_text

BUCKETS = ["클래식", "가요", "재즈", "팝", "제3세계", "클래식기타", "경음악_OST"]
UNCLASSIFIED = "미분류"

_HANGUL = re.compile(r"[가-힣]")

# bucket -> keyword substrings matched against the recovered, lowercased genre tag
_RULES: list[tuple[str, list[str]]] = [
    ("재즈", ["jazz", "swing", "bebop", "재즈"]),
    ("제3세계", ["world", "월드", "tango", "탱고", "latin", "bossa", "samba", "mpb",
              "folklore", "flamenco", "fado", "brazil", "brasil", "ethnic",
              "national folk", "제3세계"]),
    ("경음악_OST", ["ost", "o.s.t", "soundtrack", "screen music", "score", "경음악",
                 "easy listening", "instrumental", "연주", "newage", "new age"]),
    ("클래식", ["classical", "클래식", "opera", "오페라", "chamber", "symphony", "교향",
             "협주", "baroque", "romantic", "sonata", "clássica", "choral", "concerto"]),
    ("팝", ["pop", "rock", "r&b", "soul", "funk", "electronic", "dance", "hip hop",
          "hiphop", "jpop", "j-pop", "techno"]),
    ("가요", ["가요", "발라드", "ballad", "트로트", "trot", "kpop", "k-pop", "댄스"]),
]

# when multiple buckets match, the earliest here wins (and confidence drops)
_PRIORITY = ["클래식기타", "클래식", "재즈", "제3세계", "가요", "경음악_OST", "팝"]


def _kw_matches(kw: str, raw: str) -> bool:
    """Bare ASCII-alphanumeric keywords match on word boundaries (so 'ost'
    doesn't fire inside 'Post-Punk' and 'latin' not inside 'Platinum').
    Phrases, punctuated, and non-ASCII keywords match as substrings."""
    if kw.isascii() and kw.isalnum():
        return re.search(rf"\b{kw}\b", raw) is not None
    return kw in raw


@dataclass
class RuleResult:
    bucket: str
    confidence: float
    signals: str


def classify_by_rules(genres: list[str], artist: str, titles: list[str]) -> RuleResult:
    raw = " ".join((recover_text(g) or "") for g in genres).lower().strip()
    is_korean = bool(_HANGUL.search(artist or "")) or any(_HANGUL.search(t or "") for t in titles)
    has_guitar = any(k in raw for k in ("classical guitar", "클래식기타", "guitar"))

    matched: list[str] = []
    signals: list[str] = []
    for bucket, kws in _RULES:
        hit = next((kw for kw in kws if _kw_matches(kw, raw)), None)
        if hit is None:
            continue
        if bucket == "가요" and not is_korean:
            continue  # English "ballad/pop" without Korean is not 가요
        matched.append(bucket)
        signals.append(f"{bucket}:{hit}")

    if "클래식" in matched and has_guitar:
        matched = ["클래식기타" if b == "클래식" else b for b in matched]
        signals.append("guitar")
    matched = list(dict.fromkeys(matched))

    if len(matched) == 1:
        return RuleResult(matched[0], 0.9, ";".join(signals))
    if len(matched) > 1:
        chosen = next((b for b in _PRIORITY if b in matched), matched[0])
        return RuleResult(chosen, 0.5, ";".join(signals) + f";multi->{chosen}")
    if is_korean:
        return RuleResult("가요", 0.4, "no-tag;korean->가요")
    return RuleResult(UNCLASSIFIED, 0.0, f"no-tag;raw={raw!r}")
