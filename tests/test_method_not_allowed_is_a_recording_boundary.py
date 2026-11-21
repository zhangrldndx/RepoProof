"""405 是「录制的请求形状不被端点接受」,不是「主机不可用」;换端点不是降级(incident-405-misread-as-availability-*)。

d9(rich):自检、冻结、预检、正控全过;实况探针对 api.osv.dev /v1/query 的 GET 全部 405
(该端点只收 POST,而 profile 只发 GET)。探针把 405 记成 ENDPOINT_ERROR(AVAILABILITY 类,
提案「稍后重跑」),而这是录制形状的问题,永远不会「稍后」好;且非降级案例的 autopilot
对任何提案都不接受,旅程终止——可换成 GET 端点(如 pypi JSON 自带的 vulnerabilities)并不减少交付物。

不变量:
  I1 classify:405 → METHOD_NOT_ALLOWED,RECORDING 类,提案说明 profile 只发 GET、换 GET 端点或主机;
  I2 boundary_rows 带出 METHOD_NOT_ALLOWED;投影把它当作不可复用的端点(KNOWN_BOUNDARY_ENDPOINT_REUSED);
  I3 autopilot:RECORDING 类提案(端点/方法/形状)对任何案例都可接受一次——交付物不变,不是降级;
     PLATFORM_ACCESS 类仍只在 accept_boundary_proposal 下接受;
  I4 起草规则教 METHOD_NOT_ALLOWED 的处理。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from repoproof.adoption.intake import tool_drafter
from repoproof.runner import open_api_rehearsal as live
from repoproof.ui.services import autopilot


def test_405_is_a_recording_boundary_with_its_own_proposal() -> None:
    code, detail = live.classify({"content_type": "application/json", "body": b"{}"},
                                 live.LiveFetchResult(status=405, content_type="text/plain", body=b""))
    assert code == "METHOD_NOT_ALLOWED" and "405" in detail
    proposal = live.downgrade_proposal([{"host": "api.example.org", "path": "/v1/query", "query": "a=1",
                                         "code": "METHOD_NOT_ALLOWED", "detail": "HTTP 405"}])
    assert proposal["kind"] == "RECORDING" and "GET" in proposal["text"]


def test_the_boundary_row_travels_and_blocks_reuse() -> None:
    rows = autopilot.boundary_rows({"requests": [{"host": "api.example.org", "path": "/v1/query", "query": "a=1",
                                                  "code": "METHOD_NOT_ALLOWED", "detail": "HTTP 405"}]})
    assert rows and rows[0]["code"] == "METHOD_NOT_ALLOWED"
    import pytest

    with pytest.raises(tool_drafter.DraftProjectionError):
        tool_drafter._reject_known_boundary_reuse(rows, [{"blueprint_id": "b", "title": "t", "scenario": "s",
            "input_kind": "directory", "parameters": {"requests": [{"host": "api.example.org", "path": "/v1/query"}]}}])
    assert "METHOD_NOT_ALLOWED" in tool_drafter._OPEN_API_DRAFT_RULES


def _fixtures():
    spec = importlib.util.spec_from_file_location(
        "_autopilot_fixtures", Path(__file__).parent / "ui" / "test_autopilot.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _boundary(kind: str, code: str) -> dict:
    return {
        "ok": False, "verdict": "REHEARSAL_LIVE_BOUNDARY", "task_id": "tool-anon-tool-v1",
        "stages": {"rehearsal": {"verdict": "PASS_ADAPTED"}, "live_probe": {
            "status": "LIVE_BOUNDARY", "reason_codes": [code],
            "requests": [{"host": "api.example.org", "path": "/v1/query", "query": "a=1", "fixture": "anchor",
                          "status": 405, "code": code, "detail": "HTTP 405"}],
            "downgrade_proposal": {"kind": kind, "codes": [code], "text": "…"}}},
    }


class _BoundaryOnce:
    def __init__(self, inner, payload: dict) -> None:
        self.inner, self.payload, self.builds, self.adds = inner, payload, 0, 0

    def __call__(self, argv):
        argv = list(argv)
        if argv[1] == "add":
            self.adds += 1
        if argv[1] == "build":
            self.builds += 1
            if self.builds == 1:
                self.inner.calls.append(argv)
                return self.payload
        return self.inner(argv)


def _drive(tmp_path: Path, monkeypatch, *, kind: str, code: str, accept: bool):
    fixtures = _fixtures()
    _state, dest = fixtures._env(tmp_path, monkeypatch)
    runner = _BoundaryOnce(fixtures._Scripted(tmp_path, monkeypatch, payloads=fixtures._HAPPY), _boundary(kind, code))
    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon", capability="do the thing", project_root=tmp_path, dest_root=dest,
        runner=runner, record_dir=tmp_path / "record", accept_boundary_proposal=accept,
    )
    return result, runner


def test_a_recording_proposal_is_accepted_without_the_downgrade_flag(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch, kind="RECORDING", code="METHOD_NOT_ALLOWED", accept=False)
    assert result["status"] == "ACTIVE" and runner.adds == 2
    assert result["report"]["provenance"]["boundary_proposal_accepted_by"] == "autopilot"


def test_a_platform_access_proposal_still_needs_the_flag(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(
        tmp_path, monkeypatch, kind="PLATFORM_ACCESS", code="PLATFORM_REQUIRES_CREDENTIALS", accept=False
    )
    assert result["status"] == "REHEARSAL_BOUNDARY" and runner.adds == 1
