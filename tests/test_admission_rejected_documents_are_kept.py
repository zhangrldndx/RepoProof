"""准入拒绝的草稿文档也要留证(incident-admission-rejected-document-not-persisted-*)。

d1 attempt-12:带边界重起的草稿被 INPUT_SOURCE_MISMATCH(准入)拒绝,终态零诊断、文档没落盘——
DeliveryAdmissionError 按设计不进投影修复(不许模型「把需求藏起来」),但它同样是「模型写了什么」
的唯一证据;H31 只给投影拒绝留了证。没有文档,无法判断是 inputs[0].location 写成了网络,
还是 kind 写成了 file,更无法决定该教什么。

不变量:
  I1 起草循环里 DeliveryAdmissionError 抛出前带 attempts(该轮文档与 reason_code);
  I2 draft_into_bundle 对 DraftError 的落盘逻辑因此覆盖准入拒绝(同一 draft_projection_attempts.json)。
"""

from __future__ import annotations

import json

import pytest

from repoproof.adoption.intake import tool_drafter


def test_an_admission_rejection_carries_the_document(monkeypatch) -> None:
    monkeypatch.setenv("REPOPROOF_DRAFTER_MODEL", "anon-model")
    monkeypatch.setenv("REPOPROOF_DRAFTER_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("REPOPROOF_DRAFTER_KEY", "k")
    drafter = tool_drafter.LiteLLMDrafter()
    document = {"summary": "s", "delivery_requirements": {"inputs": [{"kind": "directory", "location": "remote"}]}}
    monkeypatch.setattr(drafter, "_once_with_system", lambda *_a, **_kw: json.dumps(document))

    def refuse(*_a, **_kw):
        raise tool_drafter.DeliveryAdmissionError("tool-draft:INPUT_SOURCE_MISMATCH")

    monkeypatch.setattr(tool_drafter, "normalize_draft_document", refuse)
    with pytest.raises(tool_drafter.DeliveryAdmissionError) as caught:
        drafter.draft({"capability_goal": "g", "intent_reading": None})
    attempts = getattr(caught.value, "attempts", None)
    assert attempts and attempts[0]["reason_code"] == "INPUT_SOURCE_MISMATCH"
    assert attempts[0]["document"]["delivery_requirements"]["inputs"][0]["location"] == "remote"
