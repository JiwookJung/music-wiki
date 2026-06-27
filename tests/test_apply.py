from pathlib import Path

from music_wiki.organize.apply import run_plan
from music_wiki.organize.plan import CopyOp


def test_dry_run_copies_nothing(tmp_path: Path):
    src = tmp_path / "s.mp3"
    src.write_bytes(b"audio")
    dst = tmp_path / "out" / "재즈" / "A" / "Alb" / "01 - T.mp3"
    stats = run_plan([CopyOp(str(src), str(dst))], dry_run=True)
    assert stats.planned == 1 and stats.copied == 0 and stats.skipped == 0
    assert not dst.exists()


def test_apply_copies_and_is_idempotent(tmp_path: Path):
    src = tmp_path / "s.mp3"
    src.write_bytes(b"audio")
    dst = tmp_path / "out" / "재즈" / "A" / "Alb" / "01 - T.mp3"
    ops = [CopyOp(str(src), str(dst))]
    s1 = run_plan(ops, dry_run=False)
    assert s1.copied == 1 and dst.read_bytes() == b"audio"
    s2 = run_plan(ops, dry_run=False)   # re-run
    assert s2.copied == 0 and s2.skipped == 1


def test_apply_counts_errors_and_continues(tmp_path: Path):
    good_src = tmp_path / "g.mp3"
    good_src.write_bytes(b"x")
    ops = [
        CopyOp(str(tmp_path / "missing.mp3"), str(tmp_path / "out" / "a.mp3")),  # src absent → error
        CopyOp(str(good_src), str(tmp_path / "out" / "b.mp3")),
    ]
    stats = run_plan(ops, dry_run=False)
    assert stats.errors == 1 and stats.copied == 1
