"""实况探针要分清「端点没了」与「夹具用了虚构标识」(incident-live-probe-misreads-fictional-resource-*)。

正控通过后探针对录制的三条请求真发:两个真实仓库的 /repos/{o}/{r}/pulls 回 200,夹具里虚构的
tiny/proj 回 404——探针判 ENDPOINT_GONE 并终止旅程。端点显然还在;404 的是那个不存在的资源。

不变量:
  I1 同一主机、同型路径(段数相同、首尾段相同)的请求里有 2xx 时,404/410 记为 RESOURCE_NOT_LIVE,
     不构成边界,LIVE_OK;
  I2 同型全部 404/410 → 仍是 ENDPOINT_GONE 边界——**第二起后收窄**:只有 live_anchor 夹具(真实标识)
     的 404 才判端点没了;没有 anchor 的任务不判死(见 test_open_api_live_anchor.py);
  I3 提案文本说明这是真实资源场景的答复,不是虚构标识的缘故。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoproof.execution import open_api_replay
from repoproof.runner import open_api_rehearsal as live

_HOST = "api.example.org"
_TASK = "tool-anon-v1"


def _project(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    root = tmp_path / "project"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / f"{_TASK}.yaml").write_text(
        yaml.safe_dump({"task_id": _TASK, "tool": {"workspace_contract": {"open_api_hosts": [_HOST]}}}),
        encoding="utf-8",
    )
    responses = root / "oracle" / _TASK / "fixtures" / "example-1" / "input" / open_api_replay.RESPONSES_DIRNAME
    responses.mkdir(parents=True)
    manifest = []
    for index, (path, query) in enumerate(rows):
        name = f"r{index}.json"
        (responses / name).write_text(json.dumps({"items": [1]}), encoding="utf-8")
        manifest.append({"method": "GET", "host": _HOST, "path": path, "query": query, "status": 200,
                         "content_type": "application/json", "body": name})
    open_api_replay.write_manifest(responses, manifest)
    return root


def _fetch_by_url(table: dict[str, int]):
    def fetch(url: str) -> live.LiveFetchResult:
        for needle, status in table.items():
            if needle in url:
                return live.LiveFetchResult(status=status, content_type="application/json", body=b'{"items": [1, 2]}')
        return live.LiveFetchResult(status=200, content_type="application/json", body=b'{"items": [1, 2]}')
    return fetch


def test_a_fictional_resource_beside_live_siblings_is_not_a_boundary(tmp_path: Path) -> None:
    root = _project(tmp_path, [("/repos/real/one/pulls", "state=all"), ("/repos/tiny/proj/pulls", "state=all")])
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_by_url({"tiny/proj": 404}))
    assert report["status"] == "LIVE_OK", report
    assert report["reason_codes"] == []
    codes = {row["path"]: row["code"] for row in report["requests"]}
    assert codes["/repos/tiny/proj/pulls"] == "RESOURCE_NOT_LIVE"
    assert codes["/repos/real/one/pulls"] == "OK"


def test_an_endpoint_that_is_gone_for_every_resource_stays_a_boundary(tmp_path: Path) -> None:
    root = _project(tmp_path, [("/repos/real/one/pulls", "state=all"), ("/repos/tiny/proj/pulls", "state=all")])
    archived = root / "tool_tasks" / "_drafts" / _TASK
    archived.mkdir(parents=True)
    (archived / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": "example-1", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {}, "live_anchor": True}]}), encoding="utf-8")
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_by_url({"/pulls": 404}))
    assert report["status"] == "LIVE_BOUNDARY"
    assert "ENDPOINT_GONE" in report["reason_codes"]
    assert "虚构" in report["downgrade_proposal"]["text"]
