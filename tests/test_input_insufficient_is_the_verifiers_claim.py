"""「录制不够我复算」是判官自己的断言(incident-fresh-probe-scenarios-drift-and-input-insufficient-routing-*)。

生产者已经从同一录制算出了制品;判官说 VERIFIER_INPUT_INSUFFICIENT,是判官找错了地方,不是录制
少了什么。分歧主人序列只给判官两轮,之后的修复全部发给无从下手的一方。

不变量:
  I1 分歧的子诊断含 VERIFIER_INPUT_INSUFFICIENT 时,无论第几轮都路由到判官;
  I2 其他分歧子诊断的既有序列不变。
"""

from __future__ import annotations

from repoproof.adoption.intake.draft_selfcheck import repair_target_for

_CODE = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"


def test_input_insufficient_goes_back_to_the_verifier_first() -> None:
    # Two verifier turns by construction; after that the recording is the other
    # suspect and the owners alternate (test_input_insufficient_alternates_after_two_verifier_turns.py).
    diagnostics = ("VERIFIER_INPUT_INSUFFICIENT", "VERIFIER_INPUT_INSUFFICIENT: no recorded body for x")
    assert [repair_target_for(_CODE, round_index=i, diagnostics=diagnostics) for i in (1, 2)] == ["verifier"] * 2


def test_other_disagreements_keep_their_sequence() -> None:
    first = repair_target_for(_CODE, round_index=1, diagnostics=("PUBLIC_SEMANTIC_MISMATCH",))
    third = repair_target_for(_CODE, round_index=3, diagnostics=("PUBLIC_SEMANTIC_MISMATCH",))
    assert first == "verifier" and third != "verifier"
