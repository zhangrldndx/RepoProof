"""开放 API 工具的输入按构造就是一个目录(incident-open-api-input-kind-unconstrained-*)。

夹具构建器被教导要在输入里写 __responses__/(录制),生产者要在输入里读用户的配置;
一个 file 类型的输入装不下这两样。profile 沿用 file_or_directory、提示词又没写明,模型把
输入起草成 file,构建器只能写出目录,夹具候选在 kind 校验上必然失败——与模型无关。

不变量:
  I1 open_api profile 的 admit_requirements 只接受 directory 输入(file → INPUT_SOURCE_MISMATCH);
  I2 assert_interface 同理(file → INPUT_TOPOLOGY_MISMATCH,directory 通过);
  I3 workspace_bundle_v1 行为不变(file 与 directory 都接受);
  I4 起草提示写明:开放 API 工具只取一个本地目录输入,用户的配置文件放在里面。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.delivery.product_profile import ProductProfileError, product_delivery_profile
from repoproof.adoption.intake import tool_drafter


def _requirements(kind: str, network: str) -> dict:
    return {
        "inputs": [
            {"kind": kind, "location": "local", "representation": "utf8_text", "format_label": "config", "role": "r"}
        ],
        "outputs": [{"kind": "directory", "format_id": "workspace_bundle", "format_label": "ws", "role": "r"}],
        "network": network,
        "credentials": "none",
        "lifecycle": "per_invocation",
        "runtime": "local_cpu",
    }


def test_open_api_requirements_must_take_a_directory() -> None:
    profile = product_delivery_profile("open_api_workspace_v1")
    with pytest.raises(ProductProfileError) as caught:
        profile.admit_requirements(_requirements("file", "open_api"))
    assert "INPUT_SOURCE_MISMATCH" in str(caught.value)
    admitted, _artifact = profile.admit_requirements(_requirements("directory", "open_api"))
    assert admitted.inputs[0].kind == "directory"


def test_open_api_interface_must_be_a_directory() -> None:
    profile = product_delivery_profile("open_api_workspace_v1")
    with pytest.raises(ProductProfileError) as caught:
        profile.assert_interface({"input": {"kind": "file", "format": "x"}, "output": {"kind": "directory"}})
    assert "INPUT_TOPOLOGY_MISMATCH" in str(caught.value)
    profile.assert_interface({"input": {"kind": "directory", "format": "x"}, "output": {"kind": "directory"}})


def test_the_offline_workspace_profile_is_unchanged() -> None:
    profile = product_delivery_profile("workspace_bundle_v1")
    for kind in ("file", "directory"):
        admitted, _artifact = profile.admit_requirements(_requirements(kind, "offline"))
        assert admitted.inputs[0].kind == kind
        profile.assert_interface({"input": {"kind": kind, "format": "x"}, "output": {"kind": "directory"}})


def test_the_drafting_prompt_teaches_the_directory_input() -> None:
    text = tool_drafter._SYSTEM
    lowered = text.lower()
    assert "open_api" in lowered and "directory input" in lowered
    assert "inputs[0].kind" in text or "input.kind" in text


# ---- 第二起(同一根因的另一面):Core 已知的拓扑不该再让模型猜,猜错也不该按准入拒 ----
# 复跑时模型仍把开放 API 工具的输入起草成 file,profile 以 INPUT_SOURCE_MISMATCH 按准入拒绝
# ——准入拒绝按设计不进投影自修,旅程零修复终止。输入拓扑归 Core:读数里有公共服务来源时
# 就把 directory 钉进 schema;若模型仍写 file,那是表示错误(可修),不是不受支持的需求。


def test_a_public_source_pins_the_directory_input_before_drafting() -> None:
    reading = {"data_sources": [{"name": "x", "origin": "public_service", "evidence": "e"}], "deliverables": []}
    assert tool_drafter._context_input_kind({"intent_reading": reading}) == "directory"
    offline = {"intent_reading": {"data_sources": [], "deliverables": []}, "input_kind": "file"}
    assert tool_drafter._context_input_kind(offline) == "file"


def test_the_pinned_kind_reaches_the_delivery_requirements_schema() -> None:
    schema = {
        "type": "object",
        "properties": {
            "delivery_requirements": {
                "type": "object",
                "properties": {
                    "inputs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"kind": {"type": "string", "enum": ["file", "directory"]}},
                        },
                    }
                },
            },
            "fixture_blueprints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"input_kind": {"type": "string", "enum": ["file", "directory"]}},
                },
            },
        },
    }
    pinned = tool_drafter._schema_with_pinned_input_kind(schema, "directory")
    assert pinned["properties"]["fixture_blueprints"]["items"]["properties"]["input_kind"]["enum"] == ["directory"]
    inputs = pinned["properties"]["delivery_requirements"]["properties"]["inputs"]
    assert inputs["items"]["properties"]["kind"]["enum"] == ["directory"]


def test_a_file_input_under_open_api_is_a_repairable_projection_error() -> None:
    raw = {"network": "open_api", "inputs": [{"kind": "file", "location": "local"}]}
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter._reject_file_input_for_open_api(raw)
    assert tool_drafter._projection_rejection_signature(caught.value) == (
        "OPEN_API_INPUT_MUST_BE_DIRECTORY",
        "delivery_requirements.inputs.0.kind",
    )
    tool_drafter._reject_file_input_for_open_api({"network": "open_api", "inputs": [{"kind": "directory"}]})
    tool_drafter._reject_file_input_for_open_api({"network": "offline", "inputs": [{"kind": "file"}]})
    assert "OPEN_API_INPUT_MUST_BE_DIRECTORY" in tool_drafter._PROJECTION_REPAIR_INSTRUCTION
