"""停滞预算只否决重复的尝试,不否决新出现的失败(incident-stall-budget-vetoes-a-new-failure-*)。

d5(ebooklib)attempt-5:同一签名(REFERENCE_OUTPUT_DRIFT)同一主人(reference)四轮用尽 stall 预算;第 5 轮出现
全新失败(判官归属),循环在路由前就停下——新签名一次修复机会都没有,终态与「无修复路由」长得一样。

不变量:
  I1 stall 预算耗尽后,若本轮失败是新签名(或新主人),仍给它修复;
  I2 同一签名同一主人的重复尝试仍被预算兜住(既有测试);
  I3 绝对上限仍然封顶——新签名也不能无限续命。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import (
    MAX_REPAIR_ROUNDS,
    DraftSelfCheckRepairV1,
    DraftSelfCheckRoundV1,
)
from repoproof.ui.services import product_jobs

DRIFT = ("REFERENCE_OUTPUT_DRIFT", "book.epub=BYTES_DIFFER@EPUB/content.opf")
DISAGREEMENT = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
JUDGE = ("SELECTED_ORDER_MISMATCH", "SELECTED_ORDER_MISMATCH: position 0 expected 'a' observed 'b'")


def _drive(monkeypatch, *, switch_at: int) -> tuple[list[str], list[DraftSelfCheckRoundV1]]:
    targets: list[str] = []

    def fake_round(draft_dir, draft, *, round_index, **_extra):
        if round_index < switch_at:
            return DraftSelfCheckRoundV1(
                round=round_index, check_ok=False,
                reason_codes=("WORKSPACE_REFERENCE_NOT_REPRODUCIBLE",), diagnostics=DRIFT,
            )
        return DraftSelfCheckRoundV1(
            round=round_index, check_ok=False, reason_codes=(DISAGREEMENT,), diagnostics=JUDGE,
        )

    def fake_repair(draft_dir, draft, *, target, failure, drafter, **_extra):
        targets.append(target)
        return DraftSelfCheckRepairV1(target=target, attempts=1, outcome="APPLIED")

    monkeypatch.setattr(product_jobs, "_self_check_round", fake_round)
    monkeypatch.setattr(product_jobs, "_apply_draft_control_repair", fake_repair)
    rounds = product_jobs._self_check_repair_rounds(
        Path("/nonexistent"), {}, bound=MAX_REPAIR_ROUNDS, repair=True, drafter=object()
    )
    return targets, rounds


def test_a_new_failure_after_the_stalls_still_gets_its_turn(monkeypatch) -> None:
    # The producer stalls until the budget is spent, then the judge disagrees.
    targets, rounds = _drive(monkeypatch, switch_at=MAX_REPAIR_ROUNDS + 2)
    assert targets[: MAX_REPAIR_ROUNDS + 1] == ["reference"] * (MAX_REPAIR_ROUNDS + 1)
    assert "verifier" in targets, "the new failure was never handed to its owner"
    assert rounds[-1].check_ok is False


def test_the_absolute_ceiling_still_ends_it(monkeypatch) -> None:
    targets, rounds = _drive(monkeypatch, switch_at=MAX_REPAIR_ROUNDS + 2)
    from repoproof.adoption.intake.draft_selfcheck import ABSOLUTE_REPAIR_CEILING

    assert len(targets) <= ABSOLUTE_REPAIR_CEILING
    assert len(rounds) == len(targets) + 1
