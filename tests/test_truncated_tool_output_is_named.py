"""被 max_tokens 截断的工具调用不能当成文档(incident-draft-document-missing-required-field-unexplained-*)。

d4(open-meteo)attempt-10:主起草文档三次缺 reference_impl(第一次还缺 artifact_protocol/semantic_commitments),
投影修复三次原话不变——被拒文档留证(H31)显示 JSON 合法但字段缺失。网关回复里的 stop_reason 没被读:
若模型撞了 max_tokens,工具输入就是被截断的半个文档,Harness 却把它当完整文档送进投影修复。

不变量:
  I1 GatewayReply 带 stop_reason;
  I2 stop_reason == "max_tokens" 且是强制工具调用 → AnthropicGatewayError(OUTPUT_TRUNCATED),
     detail 带 output_tokens 与上限;
  I3 起草器把它投影为 DraftError(OUTPUT_TRUNCATED),不进投影修复、不按可用性重试。
"""

from __future__ import annotations

import json

import pytest

from repoproof.agents import anthropic_gateway as gw


def _raw(stop_reason: str, arguments: dict) -> bytes:
    return json.dumps({
        "content": [{"type": "tool_use", "name": "tool_draft", "input": arguments}],
        "usage": {"input_tokens": 10, "output_tokens": 16000},
        "stop_reason": stop_reason,
    }).encode("utf-8")


def test_a_complete_tool_call_carries_its_stop_reason() -> None:
    reply = gw._reply(_raw("tool_use", {"summary": "s"}), schema={"type": "object"}, temperature_dropped=False)
    assert reply.structured and reply.stop_reason == "tool_use"


def test_a_max_tokens_tool_call_is_refused_as_truncated() -> None:
    with pytest.raises(gw.AnthropicGatewayError) as caught:
        gw._reply(_raw("max_tokens", {"summary": "s"}), schema={"type": "object"}, temperature_dropped=False)
    assert caught.value.code == "OUTPUT_TRUNCATED"
    assert "16000" in caught.value.detail


def test_the_drafter_does_not_retry_or_repair_a_truncated_output() -> None:
    from repoproof.adoption.intake import tool_drafter

    assert "OUTPUT_TRUNCATED" not in tool_drafter._GATEWAY_AVAILABILITY_CODES
