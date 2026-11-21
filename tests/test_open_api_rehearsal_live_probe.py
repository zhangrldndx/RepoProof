"""彩排要对着今天的真实主机问一次边界(m6.4 prework 8a)。

冻结前后的一切验证都对着录制跑——这是密封的代价:它证明不了"这个主机今天还这样回答"。
彩排是唯一该问实况的时刻:主机要凭证/付费了、限流了、端点没了、响应形状变了,都要在
烧真模型预算之前说出来,并给用户一份**降级提案**让其自行抉择,而不是让 Agent 对着一个
已经变了的世界修十轮。

不变量(抓取函数注入,测试永不真联网):
  I1 全部实况 2xx 且形状兼容 → LIVE_OK,并落一份实况录制(manifest + 正文)供后续审核复用;
  I2 401/402/403 → PLATFORM_REQUIRES_CREDENTIALS,提案写明需凭证/付费与"改用免凭证公共 API"的选项;
  I3 连接失败 → HOST_UNREACHABLE;429 → RATE_LIMITED;404/410 → ENDPOINT_GONE;
  I4 2xx 但缺少录制里的顶层键 → RESPONSE_SHAPE_DRIFTED,提案点名缺的键;
  I5 合同未声明主机 → NOT_APPLICABLE,不抓取任何东西;
  I6 录制里出现合同未声明的主机 → UNDECLARED_HOST_IN_RECORDING,且不向它抓取;
  I7 管线:正控通过后,边界 → REHEARSAL_LIVE_BOUNDARY(不是 PASS_ONLY);LIVE_OK → REHEARSAL_PASS_ONLY;
  I8 自动驾驶:REHEARSAL_LIVE_BOUNDARY 记为未通过、码为探针码、detail 是提案原文,状态 REHEARSAL_BOUNDARY。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoproof.execution import open_api_replay
from repoproof.runner import open_api_rehearsal as live
from repoproof.runner import tool_pipeline
from repoproof.ui.services import autopilot

_HOST = "api.anon-feeds.dev"
_TASK = "tool-anon-v1"


def _project(tmp_path: Path, *, hosts: list[str], recorded_host: str = _HOST) -> Path:
    root = tmp_path / "project"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / f"{_TASK}.yaml").write_text(
        yaml.safe_dump({"task_id": _TASK, "tool": {"workspace_contract": {"open_api_hosts": hosts}}}),
        encoding="utf-8",
    )
    responses = root / "oracle" / _TASK / "fixtures" / "example-1" / "input" / open_api_replay.RESPONSES_DIRNAME
    responses.mkdir(parents=True)
    (responses / "items.json").write_text(json.dumps({"items": [1, 2], "total": 2}), encoding="utf-8")
    open_api_replay.write_manifest(
        responses,
        [{"method": "GET", "host": recorded_host, "path": "/v1/items", "query": "limit=2",
          "status": 200, "content_type": "application/json", "body": "items.json"}],
    )
    return root


def _fetch(status: int | None, body: bytes = b"", content_type: str = "application/json", error: str = ""):
    seen: list[str] = []

    def fetch(url: str) -> live.LiveFetchResult:
        seen.append(url)
        return live.LiveFetchResult(status=status, content_type=content_type, body=body, error=error)

    fetch.seen = seen  # type: ignore[attr-defined]
    return fetch


def test_all_live_and_compatible_is_ok_and_leaves_a_recording(tmp_path: Path) -> None:
    root = _project(tmp_path, hosts=[_HOST])
    fetch = _fetch(200, json.dumps({"items": [7, 8, 9], "total": 3, "extra": True}).encode())
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live", fetch=fetch)
    assert report["status"] == "LIVE_OK", report
    assert fetch.seen == [f"https://{_HOST}/v1/items?limit=2"]
    recording = Path(report["live_recording"])
    rows = open_api_replay.load_manifest(recording)
    assert len(rows) == 1
    body = Path(next(iter(rows.values()))["body_path"])
    assert json.loads(body.read_text())["total"] == 3


def test_credentials_now_required_is_a_boundary_with_a_proposal(tmp_path: Path) -> None:
    root = _project(tmp_path, hosts=[_HOST])
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live", fetch=_fetch(402))
    assert report["status"] == "LIVE_BOUNDARY"
    assert "PLATFORM_REQUIRES_CREDENTIALS" in report["reason_codes"]
    text = report["downgrade_proposal"]["text"]
    assert _HOST in text and ("凭证" in text or "付费" in text) and "公共 API" in text


def test_unreachable_rate_limited_and_gone_are_named(tmp_path: Path) -> None:
    root = _project(tmp_path, hosts=[_HOST])
    out = tmp_path / "live"
    unreachable = live.live_probe(project_root=root, task_id=_TASK, out_root=out, fetch=_fetch(None, error="dns"))
    assert "HOST_UNREACHABLE" in unreachable["reason_codes"]
    limited = live.live_probe(project_root=root, task_id=_TASK, out_root=out, fetch=_fetch(429))
    assert "RATE_LIMITED" in limited["reason_codes"]
    # A 404 decides only for a live_anchor fixture (real identifiers); invented
    # ones say nothing about the endpoint (test_open_api_live_anchor.py).
    undecided = live.live_probe(project_root=root, task_id=_TASK, out_root=out, fetch=_fetch(404))
    assert undecided["reason_codes"] == [] and "NO_LIVE_ANCHOR_FIXTURE" in undecided["notes"]
    fixture = next(path.name for path in (root / "oracle" / _TASK / "fixtures").iterdir() if path.is_dir())
    archived = root / "tool_tasks" / "_drafts" / _TASK
    archived.mkdir(parents=True)
    (archived / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": fixture, "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {}, "live_anchor": True}]}), encoding="utf-8")
    gone = live.live_probe(project_root=root, task_id=_TASK, out_root=out, fetch=_fetch(404))
    assert "ENDPOINT_GONE" in gone["reason_codes"]


def test_a_drifted_shape_names_the_missing_keys(tmp_path: Path) -> None:
    root = _project(tmp_path, hosts=[_HOST])
    # Drift decides only for a live_anchor fixture (test_open_api_live_anchor.py).
    fixture = next(path.name for path in (root / "oracle" / _TASK / "fixtures").iterdir() if path.is_dir())
    archived = root / "tool_tasks" / "_drafts" / _TASK
    archived.mkdir(parents=True)
    (archived / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": fixture, "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {}, "live_anchor": True}]}), encoding="utf-8")
    fetch = _fetch(200, json.dumps({"results": []}).encode())
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live", fetch=fetch)
    assert report["status"] == "LIVE_BOUNDARY"
    assert "RESPONSE_SHAPE_DRIFTED" in report["reason_codes"]
    assert "items" in report["downgrade_proposal"]["text"] and "total" in report["downgrade_proposal"]["text"]


def test_an_offline_task_is_not_probed(tmp_path: Path) -> None:
    root = _project(tmp_path, hosts=[])
    fetch = _fetch(200)
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live", fetch=fetch)
    assert report["status"] == "NOT_APPLICABLE" and fetch.seen == []


def test_an_undeclared_host_in_the_recording_is_never_fetched(tmp_path: Path) -> None:
    root = _project(tmp_path, hosts=[_HOST], recorded_host="other.example.org")
    fetch = _fetch(200)
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live", fetch=fetch)
    assert "UNDECLARED_HOST_IN_RECORDING" in report["reason_codes"] and fetch.seen == []


def test_the_pipeline_turns_a_boundary_into_its_own_verdict(monkeypatch, tmp_path: Path) -> None:
    root = _project(tmp_path, hosts=[_HOST])
    boundary = {"status": "LIVE_BOUNDARY", "reason_codes": ["PLATFORM_REQUIRES_CREDENTIALS"],
                "downgrade_proposal": {"kind": "PLATFORM_ACCESS", "text": "需凭证"}}
    monkeypatch.setattr(tool_pipeline, "live_probe", lambda **_k: boundary)
    stages: dict = {"rehearsal": {"verdict": "PASS_ADAPTED"}}
    result = tool_pipeline.rehearsal_after_positive_control(
        stages=stages, task_id=_TASK, project_root=root, rehearsal_report={"verdict": "PASS_ADAPTED"}
    )
    assert result["verdict"] == "REHEARSAL_LIVE_BOUNDARY" and result["exported"] is None
    assert result["stages"]["live_probe"] == boundary

    monkeypatch.setattr(tool_pipeline, "live_probe", lambda **_k: {"status": "LIVE_OK", "reason_codes": []})
    ok = tool_pipeline.rehearsal_after_positive_control(
        stages={"rehearsal": {"verdict": "PASS_ADAPTED"}}, task_id=_TASK, project_root=root,
        rehearsal_report={"verdict": "PASS_ADAPTED"},
    )
    assert ok["verdict"] == "REHEARSAL_PASS_ONLY"


def test_the_pipeline_skips_the_probe_for_offline_tasks(monkeypatch, tmp_path: Path) -> None:
    root = _project(tmp_path, hosts=[])
    monkeypatch.setattr(tool_pipeline, "live_probe", lambda **_k: {"status": "NOT_APPLICABLE", "reason_codes": []})
    result = tool_pipeline.rehearsal_after_positive_control(
        stages={"rehearsal": {"verdict": "PASS_ADAPTED"}}, task_id=_TASK, project_root=root,
        rehearsal_report={"verdict": "PASS_ADAPTED"},
    )
    assert result["verdict"] == "REHEARSAL_PASS_ONLY"


def test_autopilot_reads_the_boundary_as_its_own_status() -> None:
    payload = {
        "verdict": "REHEARSAL_LIVE_BOUNDARY",
        "stages": {
            "rehearsal": {"verdict": "PASS_ADAPTED"},
            "live_probe": {"status": "LIVE_BOUNDARY", "reason_codes": ["PLATFORM_REQUIRES_CREDENTIALS"],
                           "downgrade_proposal": {"kind": "PLATFORM_ACCESS", "text": "主机要凭证,可改用公共 API"}},
        },
    }
    outcome = autopilot.rehearsal_outcome(payload)
    assert outcome.ok is False and outcome.status == "REHEARSAL_BOUNDARY"
    assert outcome.codes == ("PLATFORM_REQUIRES_CREDENTIALS",)
    assert outcome.detail == "主机要凭证,可改用公共 API"
    passed = autopilot.rehearsal_outcome({"verdict": "REHEARSAL_PASS_ONLY", "stages": {}})
    assert passed.ok is True and passed.status == "REHEARSAL_PASS_ONLY"
