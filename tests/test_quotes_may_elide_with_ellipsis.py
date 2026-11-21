"""省略号引文也是原话(incident-verbatim-quote-rejects-ellipsis-*)。

d3(fpdf2)三次读数被拒的取证(H30 后终于看得见):模型的 evidence 是「节假日调休...都是订阅链接」——
用省略号把一段不连续的原话连起来,每个片段都逐字出自题面;校验只认连续子串,三次全拒,
修复提示「必须是原话」对模型毫无信息(它认为这就是原话)。

不变量:
  I1 evidence 以 ... / … / ...... 分成的每个片段都是题面的逐字子串且按顺序出现 → 通过;
  I2 任一片段不在题面、或顺序颠倒 → 不通过;空片段忽略;
  I3 连续子串照旧通过;
  I4 读数提示写明可以用省略号连接不连续片段。
"""

from __future__ import annotations

from repoproof.adoption.intake import tool_drafter

_GOAL = "节假日调休、孩子学校的日历、我的排班都是订阅链接，帮我合成一面全家日历墙，冲突标红，能打印出来贴冰箱。"


def test_ellipsis_joined_fragments_count_as_a_quote() -> None:
    assert tool_drafter._quoted_from("节假日调休...都是订阅链接", _GOAL)
    assert tool_drafter._quoted_from("孩子学校的日历…订阅链接", _GOAL)
    assert tool_drafter._quoted_from("合成一面全家日历墙......能打印出来贴冰箱", _GOAL)
    assert tool_drafter._quoted_from("我的排班都是订阅链接", _GOAL)


def test_fragments_must_be_verbatim_and_in_order() -> None:
    assert not tool_drafter._quoted_from("节假日调休...订阅链接都是", _GOAL)
    assert not tool_drafter._quoted_from("能打印出来贴冰箱...节假日调休", _GOAL)
    assert not tool_drafter._quoted_from("......", _GOAL)
    assert not tool_drafter._quoted_from("", _GOAL)


def test_the_reading_prompt_allows_ellipsis() -> None:
    assert "…" in tool_drafter._INTENT_READING_SYSTEM or "..." in tool_drafter._INTENT_READING_SYSTEM
