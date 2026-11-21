"""已知边界要在起草站就对照物化后的录制检查(incident-known-boundary-reused-by-builder-code-rich-v2)。

d9(rich)attempt-8:自检的 FIXTURE_RECORDS_KNOWN_BOUNDARY 抓到构建器代码录的已证实不可用端点,但自检的修复主人
(builder/reference)改不了设计——主机/端点是起草层决定的;六轮乒乓。投影闸只按蓝图行检查,构建器代码拼请求时看不见。

不变量:
  I1 _reject_known_boundary_reuse_in_builder:有阻断类已知边界时,用本机 python 物化第一个蓝图,manifest 键命中
     → KNOWN_BOUNDARY_ENDPOINT_REUSED 投影错误(进入既有投影修复,起草者改设计);
  I2 录的是别的端点 → 放行;没有阻断类边界 → 不跑构建器;
  I3 构建器本身跑不起来 → 放行(自检会以它自己的码报告)。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    _reject_known_boundary_reuse_in_builder,
    public_validation_diagnostics,
)

_BUILDER = '''import json
from pathlib import Path


def build(blueprint, output_path):
    params = blueprint["parameters"]
    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps({"name": params["name"]}))
    responses = out / "__responses__"
    responses.mkdir()
    (responses / "b0.json").write_text("{}")
    rows = [{"method": "GET", "host": "API.example.org", "path": params["path"],
             "query": "name=%s" % params["name"], "status": 200,
             "content_type": "application/json", "body": "b0.json"}]
    (responses / "manifest.json").write_text(json.dumps({"schema_version": 1, "responses": rows}))
'''
_BLUEPRINTS = [{"blueprint_id": "one", "title": "t", "scenario": "s", "input_kind": "directory",
                "parameters": {"name": "rich", "path": "/v1/query"}}]
_WALL = [{
    "host": "api.example.org", "path": "/v1/query", "query": "", "code": "METHOD_NOT_ALLOWED", "detail": "HTTP 405",
}]


def test_a_builder_that_records_the_wall_is_a_projection_error() -> None:
    with pytest.raises(DraftProjectionError) as caught:
        _reject_known_boundary_reuse_in_builder(_WALL, _BUILDER, _BLUEPRINTS)
    assert str(caught.value) == "tool-draft:KNOWN_BOUNDARY_ENDPOINT_REUSED"
    rows = public_validation_diagnostics(caught.value)
    assert rows and rows[0]["loc"] == "fixture_builder"
    assert "api.example.org/v1/query" in rows[0]["msg"] and "METHOD_NOT_ALLOWED" in rows[0]["msg"]


def test_other_endpoints_and_soft_boundaries_pass() -> None:
    # A different path on the walled host is allowed once that family has
    # answered (incident-endpoint-guessing-on-a-walled-host-*); an unproven one
    # is a guess and is refused by the family gate.
    other = [dict(_BLUEPRINTS[0], parameters={"name": "rich", "path": "/pypi/rich/json"})]
    answered = [*_WALL] + [
        {"host": "api.example.org", "path": f"/pypi/{name}/json", "query": "", "code": "OK",
         "detail": "HTTP 200"}
        for name in ("click", "attrs")  # two observations vary the middle segment: the template is proven
    ]
    _reject_known_boundary_reuse_in_builder(answered, _BUILDER, other)
    with pytest.raises(DraftProjectionError) as guessed:
        _reject_known_boundary_reuse_in_builder(_WALL, _BUILDER, other)
    assert str(guessed.value) == "tool-draft:OPEN_API_PATH_UNPROVEN_ON_WALLED_HOST"
    soft = [dict(_WALL[0], code="RESPONSE_SHAPE_DRIFTED")]
    _reject_known_boundary_reuse_in_builder(soft, _BUILDER, _BLUEPRINTS)
    _reject_known_boundary_reuse_in_builder([], _BUILDER, _BLUEPRINTS)


def test_a_broken_builder_is_left_to_the_self_check() -> None:
    broken = "def build(blueprint, output_path):\n    raise RuntimeError('x')\n"
    _reject_known_boundary_reuse_in_builder(_WALL, broken, _BLUEPRINTS)
