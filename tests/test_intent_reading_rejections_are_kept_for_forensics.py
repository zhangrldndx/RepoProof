"""被拒的读数要留在草稿束里,报告要把字段诊断摘成一句(incident-intent-reading-rejected-document-not-persisted-*)。

d3(fpdf2)与 d6(altair)都在读数处以 DELIVERABLE_EVIDENCE_NOT_IN_REQUEST 终止三次——H23 之后
终态说出了规则与字段,但模型到底写了什么 evidence、为什么不是原话,盘上没有:公开诊断按设计不含
模型输入值,而读数文档本身也没有落盘;报告的 facts 又把列表丢掉,只剩 admission_status。

不变量:
  I1 read_intent 用尽尝试后,DraftError.attempts 带每次的文档与拒绝(reason_code + 字段诊断);
  I2 persist_intent_reading_attempts 把它们写进草稿束 intent_reading_attempts.json(私有取证,不进公开诊断);
  I3 autopilot 起草失败记录的 facts 带 validation_errors_summary(loc: msg 摘要,有界)。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from repoproof.adoption.intake import tool_drafter
from repoproof.ui.services import autopilot

_GOAL = "几种货币的汇率每天看一眼,到我设的价位提醒我,能看趋势"


class _Drafter:
    def __init__(self, document: dict) -> None:
        self._document = document

    def _structured(self, *, instructions: str, context: dict, schema: dict, purpose: str) -> dict:
        return self._document


def _reading(evidence: str) -> dict:
    return {
        "data_sources": [{"name": "rates", "origin": "public_service", "evidence": "汇率"}],
        "deliverables": [{"name": "board", "form": "dashboard_html", "evidence": evidence}],
    }


def test_the_terminal_carries_every_rejected_reading(tmp_path: Path) -> None:
    with pytest.raises(tool_drafter.DraftError) as caught:
        tool_drafter.read_intent(_Drafter(_reading("汇率趋势看板")), _GOAL)
    attempts = caught.value.attempts
    assert len(attempts) == tool_drafter._INTENT_READING_ATTEMPTS
    assert attempts[0]["document"]["deliverables"][0]["evidence"] == "汇率趋势看板"
    assert attempts[0]["reason_code"] == "DELIVERABLE_EVIDENCE_NOT_IN_REQUEST"
    assert attempts[0]["public_validation_errors"][0]["loc"] == "deliverables.0.evidence"
    path = tool_drafter.persist_intent_reading_attempts(tmp_path, caught.value)
    assert path == tmp_path / "intent_reading_attempts.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["capability_goal"] == _GOAL
    assert len(stored["attempts"]) == tool_drafter._INTENT_READING_ATTEMPTS


def test_the_autopilot_report_summarises_the_field_diagnostics(tmp_path: Path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "_autopilot_fixtures", Path(__file__).parent / "ui" / "test_autopilot.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(fixtures)
    _state, dest = fixtures._env(tmp_path, monkeypatch)
    payloads = {
        **fixtures._HAPPY,
        "add": {
            "ok": False,
            "admission": {"status": "RISK_REVIEW"},
            "draft_error": "tool-draft:INTENT_READING_INVALID",
            "draft_error_diagnostics": [
                {"loc": "intent_reading", "type": "x", "msg": "Core rejected every one of 3 readings"},
                {"loc": "deliverables.0.evidence", "type": "deliverable_evidence_not_in_request",
                 "msg": "evidence must be a verbatim quote"},
            ],
        },
    }
    runner = fixtures._Scripted(tmp_path, monkeypatch, payloads=payloads)
    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon", capability="do the thing", project_root=tmp_path,
        dest_root=dest, runner=runner, record_dir=tmp_path / "record",
    )
    assert result["status"] == "DRAFT_FAILED"
    draft = next(s for s in result["report"]["stages"] if s["stage"] == "draft")
    summary = draft["facts"]["validation_errors_summary"]
    assert "deliverables.0.evidence" in summary and "verbatim" in summary
