"""工作区交付的输出拓扑是 Core 已知的事实(incident-output-format-guess-rejected-at-admission-*)。

读数里已有非文本交付物(仪表盘页面),模型仍给 outputs[0] 写了 profile 里没有的 format_id,
准入以 OUTPUT_FORMAT_NOT_IN_PROFILE 拒绝——准入拒绝不进投影自修,旅程三分钟终止。
与输入拓扑同型:Core 已知的拓扑不该让模型猜,猜错也不该按「不受支持」处理。

不变量:
  I1 读数含非文本交付物 → _context_output_topology 判定为工作区,schema 钉住
     outputs[].kind=directory 与 outputs[].format_id=workspace_bundle;
  I2 目录交付而 format_id 不是 workspace_bundle → 投影拒绝 OUTPUT_FORMAT_ID_NOT_WORKSPACE_BUNDLE
     (签名 delivery_requirements.outputs.0.format_id);正确时通过;文本交付不受影响;
  I3 修复说明写明该码的改法。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake import tool_drafter


def test_visual_deliverables_pin_the_workspace_output_in_the_schema() -> None:
    schema = {
        "type": "object",
        "properties": {
            "delivery_requirements": {
                "type": "object",
                "properties": {
                    "outputs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["text_artifact", "directory"]},
                                "format_id": {"type": "string"},
                            },
                        },
                    }
                },
            }
        },
    }
    reading = {"data_sources": [], "deliverables": [{"name": "board", "form": "dashboard_html", "evidence": "e"}]}
    assert tool_drafter._context_wants_workspace({"intent_reading": reading}) is True
    pinned = tool_drafter._schema_with_pinned_output_topology(schema, workspace=True)
    items = pinned["properties"]["delivery_requirements"]["properties"]["outputs"]["items"]["properties"]
    assert items["kind"]["enum"] == ["directory"] and items["format_id"]["enum"] == ["workspace_bundle"]
    text_only = {"data_sources": [], "deliverables": [{"name": "n", "form": "markdown", "evidence": "e"}]}
    assert tool_drafter._context_wants_workspace({"intent_reading": text_only}) is False
    assert tool_drafter._schema_with_pinned_output_topology(schema, workspace=False) == schema


def test_a_wrong_format_id_for_a_directory_is_a_repairable_projection_error() -> None:
    raw = {"outputs": [{"kind": "directory", "format_id": "dashboard_html"}]}
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter._reject_non_bundle_format_for_workspace(raw)
    assert tool_drafter._projection_rejection_signature(caught.value) == (
        "OUTPUT_FORMAT_ID_NOT_WORKSPACE_BUNDLE",
        "delivery_requirements.outputs.0.format_id",
    )
    tool_drafter._reject_non_bundle_format_for_workspace(
        {"outputs": [{"kind": "directory", "format_id": "workspace_bundle"}]}
    )
    tool_drafter._reject_non_bundle_format_for_workspace({"outputs": [{"kind": "text_artifact", "format_id": "csv"}]})
    assert "OUTPUT_FORMAT_ID_NOT_WORKSPACE_BUNDLE" in tool_drafter._PROJECTION_REPAIR_INSTRUCTION
