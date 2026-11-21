"""「判官说输入不够」先归判官,判官两轮无果后要轮到构建器(incident-input-insufficient-never-leaves-the-verifier-*)。

H20(bokeh):判官按自己想象的端点说「录制缺 X」,按构造归判官——对。
这一起(open-meteo,FlatBuffers 录制体):判官五轮「没有录制体能解出 temperature/precipitation/wind_speed」,
五次修复全给判官,原话每轮略变、停滞检测不响,预算用尽;而录制体是模型用猜测的 SDK API 写出来的
二进制,构建器一次也没被问过。判官的主张仍可能是对的:输入(录制)真的解不出来。

不变量:
  I1 VERIFIER_INPUT_INSUFFICIENT 的第 1、2 轮归判官(H20 不变);
  I2 第 3 轮起交替:3 → builder,4 → verifier,5 → builder …;
  I3 其他按构造归判官的标记(_BINDING_CONTROL_FAILED / VERIFIER_INFORMATIONAL_)不受影响,始终判官。
"""

from __future__ import annotations

from repoproof.adoption.intake import draft_selfcheck

_CODE = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
_INSUFFICIENT = ("VERIFIER_INPUT_INSUFFICIENT", "VERIFIER_INPUT_INSUFFICIENT: no recorded body decodes X")


def test_input_insufficient_goes_to_the_verifier_twice_then_alternates() -> None:
    owners = [
        draft_selfcheck.repair_target_for(_CODE, round_index=i, diagnostics=_INSUFFICIENT) for i in range(1, 7)
    ]
    assert owners == ["verifier", "verifier", "builder", "verifier", "builder", "verifier"], owners


def test_binding_control_markers_stay_with_the_verifier() -> None:
    marker = ("INPUT_BINDING_CONTROL_FAILED", "INPUT_BINDING_CONTROL_FAILED: the verifier still accepted")
    owners = {draft_selfcheck.repair_target_for(_CODE, round_index=i, diagnostics=marker) for i in range(1, 7)}
    assert owners == {"verifier"}
