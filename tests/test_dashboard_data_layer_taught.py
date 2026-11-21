"""仪表盘的数据层要先教后问(m6.4 prework 10)。

判别力探针现在会改内嵌 JSON 里的数值;判官若只看渲染出的标记或图表库样板,必然放过——
那是探针要杀的。闸门要杀的先教:起草提示写明数据层的形态与协议定位;判官提示写明从
数据层复算。
"""

from __future__ import annotations

from repoproof.adoption.intake import tool_drafter


def test_drafting_prompt_teaches_the_data_layer() -> None:
    text = tool_drafter._SYSTEM
    assert "application/json" in text and "data layer" in text
    assert "artifact_protocol" in text and "CDN" in text


def test_verifier_prompts_teach_recomputation_from_the_data_layer() -> None:
    for text in (tool_drafter._VERIFIER_SYSTEM, tool_drafter._VERIFIER_REPAIR_SYSTEM):
        assert "data layer" in text and "application/json" in text
        assert "recomputation" in text
