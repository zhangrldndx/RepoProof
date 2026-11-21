"""「判官没调上游」按构造归判官,且修复提示要说清楚(incident-upstream-call-not-observed-routed-to-producer-*)。

d4(open-meteo)attempt-9:判官用标准库手工解 FlatBuffers,一次都没 import 上游;UPSTREAM_CALL_NOT_OBSERVED
四轮:判官两轮没改过来,后两轮却给了生产者——这个码说的是判官自己的构造(判官的裁决必须依赖上游返回的值),
生产者改什么都不会让判官去调上游。

不变量:
  I1 分歧诊断含 UPSTREAM_CALL_NOT_OBSERVED → 任何轮次都路由 verifier;
  I2 判官修复提示写明该码的含义与修法(import 并真正调用钉版上游来重算/解码)。
"""

from __future__ import annotations

from repoproof.adoption.intake import draft_selfcheck, tool_drafter

_CODE = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
_MARK = ("UPSTREAM_CALL_NOT_OBSERVED", "UPSTREAM_CALL_NOT_OBSERVED: the verifier finished without a recorded call")


def test_no_upstream_call_is_always_the_verifiers_turn() -> None:
    owners = {draft_selfcheck.repair_target_for(_CODE, round_index=i, diagnostics=_MARK) for i in range(1, 8)}
    assert owners == {"verifier"}


def test_the_verifier_repair_rules_explain_the_code() -> None:
    assert "UPSTREAM_CALL_NOT_OBSERVED" in tool_drafter._VERIFIER_REPAIR_SYSTEM
