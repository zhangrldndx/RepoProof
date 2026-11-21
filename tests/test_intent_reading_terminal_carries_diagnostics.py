"""读数终态要说出是哪条规则拒的(incident-intent-reading-terminal-without-diagnostics-*)。

d3 attempt-4:三次读数都被 Core 拒,每次的 reason_code 与字段诊断都喂回了模型,最终 DraftError
却一个都没带——报告 detail 只有 INTENT_READING_INVALID,draft_error_diagnostics 为空。
DraftError 的契约:diagnostics 承载 Core 字段级拒绝事实,失败的草稿要能从盘上的报告诊断。

不变量:
  I1 read_intent 用尽尝试后抛出的 DraftError.diagnostics 非空:含最后一次拒绝的 reason_code、
     字段 loc/msg(不含模型输入值)与尝试次数;
  I2 每次重试的上下文仍带 core_projection_repair(既有行为不变);
  I3 读数一次通过时不受影响。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake import tool_drafter

_GOAL = "帮我把订阅链接合成一面日历墙,冲突标红"


class _Drafter:
    def __init__(self, documents: list[dict]) -> None:
        self._documents = list(documents)
        self.contexts: list[dict] = []

    def _structured(self, *, instructions: str, context: dict, schema: dict, purpose: str) -> dict:
        self.contexts.append(context)
        return self._documents.pop(0) if len(self._documents) > 1 else self._documents[0]


def _reading(evidence: str) -> dict:
    return {
        "data_sources": [{"name": "feeds", "origin": "public_service", "evidence": "订阅链接"}],
        "deliverables": [{"name": "wall", "form": "pdf", "evidence": evidence}],
    }


def test_an_exhausted_reading_names_the_rule_it_broke() -> None:
    drafter = _Drafter([_reading("一面漂亮的海报")])  # never a quote from the request
    with pytest.raises(tool_drafter.DraftError) as caught:
        tool_drafter.read_intent(drafter, _GOAL)
    assert str(caught.value) == "tool-draft:INTENT_READING_INVALID"
    rows = caught.value.diagnostics
    assert rows, "the terminal must carry the last rejection"
    text = " ".join(f"{row.get('loc')} {row.get('type')} {row.get('msg')}" for row in rows)
    assert "deliverable_evidence_not_in_request" in text.lower()
    assert "deliverables.0.evidence" in text
    assert str(tool_drafter._INTENT_READING_ATTEMPTS) in text
    assert "海报" not in text  # never the model's input value
    assert len(drafter.contexts) == tool_drafter._INTENT_READING_ATTEMPTS
    assert all("core_projection_repair" in ctx for ctx in drafter.contexts[1:])


def test_a_reading_that_passes_is_untouched() -> None:
    drafter = _Drafter([_reading("日历墙")])
    reading = tool_drafter.read_intent(drafter, _GOAL)
    assert reading["deliverables"][0]["evidence"] == "日历墙"
    assert len(drafter.contexts) == 1
