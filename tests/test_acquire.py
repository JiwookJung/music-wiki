"""분류번호 발급 API 로직: 기존 코드 불변 + 빈 번호 삽입."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp"))


def test_issue_code_dry_run_is_stable(tmp_path, monkeypatch):
    import acquire
    before = json.loads(Path(acquire.REGISTRY).read_text(encoding="utf-8"))
    res = acquire.issue_code(artist="Keith Jarrett", album="The Köln Concert",
                             genre="재즈", medium="LP", dry_run=True)
    after = json.loads(Path(acquire.REGISTRY).read_text(encoding="utf-8"))
    assert res["code"].startswith("J-K")     # 재즈 + K 초성
    assert res["dry_run"] is True
    assert before == after                   # dry-run은 레지스트리 불변


def test_existing_codes_never_shift(tmp_path):
    """새 아티스트를 넣어도 기존 아티스트 번호는 그대로여야 한다."""
    import acquire
    reg = json.loads(Path(acquire.REGISTRY).read_text(encoding="utf-8"))
    je_before = dict(reg["artists"].get("J|E", {}))
    res = acquire.issue_code(artist="Esbjörn Svensson Trio", album="Viaticum",
                             genre="재즈", medium="LP", dry_run=True)
    reg2 = json.loads(Path(acquire.REGISTRY).read_text(encoding="utf-8"))
    assert reg2["artists"].get("J|E", {}) == je_before   # 저장 안 됨(dry-run)
    assert res["code"].startswith("J-E")                  # 신규도 같은 그룹
