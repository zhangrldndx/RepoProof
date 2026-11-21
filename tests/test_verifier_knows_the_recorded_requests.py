"""判官要被告知夹具录了哪些请求(incident-verifier-not-told-the-recorded-requests-*)。

判官被要求「从 input/__responses__ 独立复算」,却没被告知录制里有哪些请求键;它按自己想象的
端点去找,九轮报「录制缺少 X」,生产者/构建器/合同修了六次都无从下手——录制请求集是公开事实。

不变量:
  I1 从蓝图参数的请求行(host+path+query)抽出规范化的请求键列表(去重、排序);
  I2 判官起草上下文带 recorded_requests;判官修复上下文(自检公开上下文)也带;
  I3 判官提示写明:录制定义请求集,只按 manifest 里实际存在的键读正文,绝不要求录制里没有的端点,
     无法从任何录制正文复算的承诺以 VERIFIER_INPUT_INSUFFICIENT 点名。
"""

from __future__ import annotations

import json
from pathlib import Path

from repoproof.adoption.intake import tool_drafter
from repoproof.ui.services import product_jobs

_BLUEPRINTS = [
    {"blueprint_id": "b1", "title": "t", "scenario": "s", "input_kind": "directory", "parameters": {
        "handle": "anon",
        "recordings": [
            {"host": "api.example.org", "path": "/v1/items", "query": {"q": "x", "limit": 2}, "body": {"items": []}},
            {"host": "feeds.example.org", "path": "feed.xml", "query": {}, "body": "<rss/>"},
        ],
    }},
    {"blueprint_id": "b2", "title": "t", "scenario": "s", "input_kind": "directory", "parameters": {
        "recordings": [{"host": "api.example.org", "path": "/v1/items", "query": {"limit": 2, "q": "x"}, "body": {}}],
    }},
]


def test_request_keys_are_extracted_canonically() -> None:
    keys = tool_drafter.recorded_request_keys(_BLUEPRINTS)
    assert keys == ["GET api.example.org/v1/items?limit=2&q=x", "GET feeds.example.org/feed.xml"]


def test_the_verifier_drafting_context_carries_the_recorded_requests() -> None:
    drafted = {
        "capability_goal": "g",
        "semantic_commitments": [],
        "artifact_protocol": {"schema_version": 1, "protocol_id": "p", "observations": []},
        "delivery_requirements": {}, "delivery_profile": "open_api_workspace_v1", "input_format": "dir",
        "output_format_id": "workspace_bundle", "output_format": "workspace", "output_contract": None,
        "workspace_contract": {"rules": []}, "fixture_blueprints": _BLUEPRINTS,
    }
    context = tool_drafter._verifier_context({"capability_goal": "g"}, drafted)
    assert context["recorded_requests"] == tool_drafter.recorded_request_keys(_BLUEPRINTS)


def test_the_repair_context_reads_the_blueprints_on_disk(tmp_path: Path) -> None:
    (tmp_path / "fixture_blueprints.json").write_text(
        json.dumps({"schema_version": 1, "blueprints": _BLUEPRINTS}), encoding="utf-8"
    )
    assert product_jobs._recorded_requests_for_draft(tmp_path) == tool_drafter.recorded_request_keys(_BLUEPRINTS)
    assert product_jobs._recorded_requests_for_draft(tmp_path / "missing") == []


def test_the_verifier_prompts_teach_the_recording_as_given() -> None:
    for text in (tool_drafter._VERIFIER_SYSTEM, tool_drafter._VERIFIER_REPAIR_SYSTEM):
        assert "recorded_requests" in text
        assert "VERIFIER_INPUT_INSUFFICIENT" in text
        lowered = text.lower()
        assert "never require" in lowered or "never demand" in lowered
