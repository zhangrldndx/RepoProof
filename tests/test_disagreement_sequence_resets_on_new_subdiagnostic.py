"""分歧主人序列按(码, 首个子诊断)计数:子诊断变了,判官重新先答(incident-disagreement-sequence-not-reset-*)。

d1(plotly)与 d3(fpdf2):同一个码 WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT 下,前两三轮是
一个子诊断(判官的两轮用掉),之后换成另一个子诊断(期望为空 / PDF 抽不到数字),新子诊断的七轮全给了
生产者/合同/构建器,判官一轮都没有。

不变量:
  I1 _same_failure_repairs 只数「同码且同首个子诊断」的既往修复;
  I2 子诊断变了 → 计数归零 → repair_target_for 从判官重新开始;
  I3 非分歧码(只有码没有子诊断)行为不变:按同码计数。
"""

from __future__ import annotations

from repoproof.adoption.intake.draft_selfcheck import DraftSelfCheckRepairV1, DraftSelfCheckRoundV1
from repoproof.ui.services import product_jobs

_CODE = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"


def _round(index: int, code: str, first_diag: str, target: str) -> DraftSelfCheckRoundV1:
    return DraftSelfCheckRoundV1(
        round=index, check_ok=False, reason_codes=(code,), diagnostics=(first_diag, f"{first_diag}: detail"),
        repair=DraftSelfCheckRepairV1(target=target, attempts=1, outcome="APPLIED"),
    )


def test_a_new_subdiagnostic_restarts_the_owner_sequence() -> None:
    rounds = [_round(1, _CODE, "VERIFIER_INPUT_INSUFFICIENT", "verifier"),
              _round(2, _CODE, "VERIFIER_INPUT_INSUFFICIENT", "verifier")]
    same = DraftSelfCheckRoundV1(round=3, check_ok=False, reason_codes=(_CODE,),
                                 diagnostics=("VERIFIER_INPUT_INSUFFICIENT", "VERIFIER_INPUT_INSUFFICIENT: x"))
    changed = DraftSelfCheckRoundV1(round=3, check_ok=False, reason_codes=(_CODE,),
                                    diagnostics=("PDF_GRID_INCOMPLETE", "PDF_GRID_INCOMPLETE: 0 day numbers"))
    assert product_jobs._same_failure_repairs(rounds, same) == 2
    assert product_jobs._same_failure_repairs(rounds, changed) == 0


def test_codes_without_subdiagnostics_still_count_by_code() -> None:
    rounds = [_round(1, "WORKSPACE_REFERENCE_EXECUTION_FAILED", "TypeError", "reference"),
              _round(2, "WORKSPACE_REFERENCE_EXECUTION_FAILED", "ValueError", "reference")]
    check = DraftSelfCheckRoundV1(round=3, check_ok=False, reason_codes=("WORKSPACE_REFERENCE_EXECUTION_FAILED",),
                                  diagnostics=("KeyError",))
    assert product_jobs._same_failure_repairs(rounds, check) == 2
