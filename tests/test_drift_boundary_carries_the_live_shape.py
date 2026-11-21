"""形状漂移的边界要带上实况的形状,重起才知道该录成什么样(incident-drift-redraft-without-live-shape-*)。

d1(plotly)第二段:带着 known_boundaries 重起后,Bluesky 换成了免凭证端点(200),
GitHub 200,但 HN 的 anchor item 仍然「缺少录制依赖的字段:text」——边界行只说缺哪个字段,
没说实况长什么样,模型又按自己的想象录了一次。

不变量:
  I1 探针的 RESPONSE_SHAPE_DRIFTED 行带 live_shape(实况 JSON 的有界形状);
  I2 autopilot.boundary_rows 原样带出 live_shape;
  I3 起草规则教:漂移行按 live_shape 录制。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoproof.adoption.intake import tool_drafter
from repoproof.execution import open_api_replay
from repoproof.runner import open_api_rehearsal as live
from repoproof.ui.services import autopilot

_HOST = "api.anon-feeds.dev"
_TASK = "tool-anon-v1"


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / f"{_TASK}.yaml").write_text(
        yaml.safe_dump({"task_id": _TASK, "tool": {"workspace_contract": {"open_api_hosts": [_HOST]}}}),
        encoding="utf-8",
    )
    responses = root / "oracle" / _TASK / "fixtures" / "anchor" / "input" / open_api_replay.RESPONSES_DIRNAME
    responses.mkdir(parents=True)
    (responses / "r0.json").write_text(json.dumps({"id": 1, "text": "hello", "by": "x"}), encoding="utf-8")
    open_api_replay.write_manifest(responses, [{"method": "GET", "host": _HOST, "path": "/v0/item/1.json", "query": "",
                                                "status": 200, "content_type": "application/json", "body": "r0.json"}])
    archived = root / "tool_tasks" / "_drafts" / _TASK
    archived.mkdir(parents=True)
    (archived / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": "anchor", "title": "t", "scenario": "s", "input_kind": "directory", "parameters": {},
         "live_anchor": True}]}), encoding="utf-8")
    return root


def test_a_drifted_anchor_row_carries_the_live_shape(tmp_path: Path) -> None:
    root = _project(tmp_path)
    body = json.dumps({"id": 1, "title": "Story", "url": "https://x", "kids": [2, 3]}).encode()

    def fetch(url: str) -> live.LiveFetchResult:
        return live.LiveFetchResult(status=200, content_type="application/json", body=body)

    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live", fetch=fetch)
    assert report["reason_codes"] == ["RESPONSE_SHAPE_DRIFTED"]
    row = report["requests"][0]
    assert row["live_shape"] == {"id": "int", "title": "str", "url": "str", "kids": "array[2]"}
    rows = autopilot.boundary_rows(report)
    assert rows[0]["live_shape"] == row["live_shape"]


def test_the_rules_teach_recording_the_live_shape() -> None:
    assert "live_shape" in tool_drafter._OPEN_API_DRAFT_RULES
