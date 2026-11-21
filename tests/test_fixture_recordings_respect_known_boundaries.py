"""构建器代码拼出的请求也不许录已证实不可用的端点(incident-known-boundary-reused-by-builder-code-*)。

d9(rich):彩排证实 GET api…/v1/vulns 已不存在,autopilot 代用户接受换端点提案并带 known_boundaries 重起草;
重起草的蓝图参数里没有 host/path 行——请求由 fixture_builder 代码拼出——投影闸只看蓝图行,放行;物化后的
manifest 仍录同一个端点,两次旅程都在同一堵墙上第二次撞终态。

不变量:
  I1 assert_recordings_avoid_known_boundaries(fixture, boundaries, fixture_id):manifest 里 GET host+path 命中
     阻断类边界(PLATFORM_REQUIRES_CREDENTIALS/ENDPOINT_GONE/METHOD_NOT_ALLOWED)→ FIXTURE_RECORDS_KNOWN_BOUNDARY,
     诊断点名端点与边界码;非阻断类(形状漂移)与无 manifest 不报;
  I2 known_boundaries_for_draft(draft_dir) 读草稿束的 known_boundaries.json;没有 → [];
  I3 路由:构建器先修(它录制),生产者交替(它也在调那个端点)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.adoption.intake import draft_selfcheck
from repoproof.adoption.intake.workspace_fixtures import assert_recordings_avoid_known_boundaries
from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import product_jobs


def _fixture(tmp_path: Path, rows: list[dict]) -> Path:
    root = tmp_path / "fixture"
    (root / "__responses__").mkdir(parents=True)
    (root / "__responses__" / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "responses": rows}), encoding="utf-8"
    )
    return root


_GONE = {
    "host": "api.example.org", "path": "/v1/vulns", "query": "name=x", "code": "ENDPOINT_GONE", "detail": "HTTP 404",
}
_DRIFT = {"host": "api.example.org", "path": "/v1/query", "query": "", "code": "RESPONSE_SHAPE_DRIFTED", "detail": ""}


def _row(host: str, path: str, query: str = "") -> dict:
    return {"method": "GET", "host": host, "path": path, "query": query, "status": 200, "body": "b.json"}


def test_a_recording_on_a_gone_endpoint_is_refused(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, [
        _row("pypi.example.org", "/pypi/a/json"),
        _row("API.example.org", "v1/vulns", "name=a&ecosystem=PyPI"),
    ])
    with pytest.raises(WorkspaceBundleError) as caught:
        assert_recordings_avoid_known_boundaries(fixture, [_GONE, _DRIFT], fixture_id="all-current")
    assert caught.value.code == "FIXTURE_RECORDS_KNOWN_BOUNDARY"
    text = " ".join(caught.value.diagnostics)
    assert "api.example.org/v1/vulns" in text and "ENDPOINT_GONE" in text and "all-current" in text


def test_drifted_shapes_and_other_paths_are_not_walls(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, [
        _row("api.example.org", "/v1/query"),
        _row("api.example.org", "/v1/vulns/GHSA-1"),
    ])
    assert_recordings_avoid_known_boundaries(fixture, [_GONE, _DRIFT], fixture_id="f")
    assert_recordings_avoid_known_boundaries(tmp_path / "missing", [_GONE], fixture_id="f")
    assert_recordings_avoid_known_boundaries(fixture, [], fixture_id="f")


def test_known_boundaries_are_read_from_the_draft(tmp_path: Path) -> None:
    assert product_jobs.known_boundaries_for_draft(tmp_path) == []
    (tmp_path / "known_boundaries.json").write_text(
        json.dumps({"schema_version": 1, "boundaries": [_GONE, "junk"]}), encoding="utf-8"
    )
    assert product_jobs.known_boundaries_for_draft(tmp_path) == [_GONE]


def test_the_builder_answers_first_then_the_producer() -> None:
    targets = [draft_selfcheck.repair_target_for("FIXTURE_RECORDS_KNOWN_BOUNDARY", round_index=i) for i in range(1, 5)]
    assert targets == ["builder", "reference", "builder", "reference"]
