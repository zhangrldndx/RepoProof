"""彩排边界提案要有产品路径:接受提案 = 带着已知边界重新起草(incident-boundary-proposal-has-no-retry-path-*)。

d1(plotly,两次):实况探针确定 Bluesky searchPosts 无凭证 403,提案 ②「改用免凭证公共端点重新
起草(新任务版本)」——但没有任何路径把这条边界带进新草稿:autopilot 只在准入反提案处代用户接受
一次,彩排边界没有等价物;用户同样只能重打一遍题面、模型再猜一遍同一个端点。

不变量(起草侧):
  I1 tool add 接受 known_boundaries(host/path/code/detail 行),进入起草上下文;起草规则教「不得再请求这些端点」;
  I2 投影:蓝图请求行命中 PLATFORM_REQUIRES_CREDENTIALS / ENDPOINT_GONE 的已知边界(同 host+path)→
     KNOWN_BOUNDARY_ENDPOINT_REUSED(可修);RESPONSE_SHAPE_DRIFTED 行只作事实不硬拒;修复指引写明;
  I3 没有已知边界时行为不变。
"""

from __future__ import annotations

import inspect
import json

import pytest

from repoproof.adoption.intake import tool_drafter

_BLOCKED = {"host": "api.example.org", "path": "/xrpc/search", "query": "q=x", "code": "PLATFORM_REQUIRES_CREDENTIALS",
            "detail": "HTTP 403"}
_DRIFTED = {"host": "api.example.org", "path": "/v0/item", "query": "", "code": "RESPONSE_SHAPE_DRIFTED",
            "detail": "missing text"}


def _blueprints(path: str) -> list[dict]:
    return [{"blueprint_id": "b1", "title": "t", "scenario": "s", "input_kind": "directory",
             "parameters": {"requests": [{"host": "api.example.org", "path": path, "query": "q=y"}]}}]


def test_reusing_a_blocked_endpoint_is_a_repairable_projection_error() -> None:
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter._reject_known_boundary_reuse([_BLOCKED], _blueprints("/xrpc/search"))
    assert tool_drafter._projection_rejection_signature(caught.value) == (
        "KNOWN_BOUNDARY_ENDPOINT_REUSED",
        "fixture_blueprints",
    )
    tool_drafter._reject_known_boundary_reuse([_BLOCKED], _blueprints("/xrpc/feed"))
    tool_drafter._reject_known_boundary_reuse([_DRIFTED], _blueprints("/v0/item"))  # facts, not a wall
    tool_drafter._reject_known_boundary_reuse([], _blueprints("/xrpc/search"))
    tool_drafter._reject_known_boundary_reuse(None, _blueprints("/xrpc/search"))


def test_the_projection_and_repair_context_take_known_boundaries() -> None:
    assert "known_boundaries" in inspect.signature(tool_drafter.normalize_draft_document).parameters
    assert "known_boundaries" in inspect.signature(tool_drafter._projection_repair_context).parameters
    assert "known_boundaries" in inspect.signature(tool_drafter.draft_into_bundle).parameters


def test_the_rules_teach_known_boundaries() -> None:
    assert "known_boundaries" in tool_drafter._OPEN_API_DRAFT_RULES
    assert "KNOWN_BOUNDARY_ENDPOINT_REUSED" in tool_drafter._PROJECTION_REPAIR_INSTRUCTION


def test_the_cli_accepts_known_boundaries_json() -> None:
    from repoproof import cli

    parser = cli.build_parser()
    args = parser.parse_args(["tool", "add", "--repo", "r", "--capability", "c", "--draft-out", "d",
                              "--known-boundaries-json", json.dumps([_BLOCKED])])
    assert json.loads(args.known_boundaries_json)[0]["code"] == "PLATFORM_REQUIRES_CREDENTIALS"
    auto = parser.parse_args(["tool", "autopilot", "--repo", "r", "--capability", "c", "--accept-boundary-proposal"])
    assert auto.accept_boundary_proposal is True
