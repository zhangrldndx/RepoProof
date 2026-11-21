"""判官要被告知回放清单的确切形状(incident-verifier-not-told-the-recorded-requests-*,第三面)。

d1(plotly)重起段:判官八轮「no recorded response bodies parsed under __responses__」——它读
manifest.get("requests", manifest.get("rows"));清单的键是 "responses"。构建器规则写明了
{"schema_version": 1, "responses": [row, ...]},判官规则没有。

不变量:
  I1 _OPEN_API_VERIFIER_RULES 写明清单文档形状与行字段(responses / method host path query status content_type body);
  I2 判官修复上下文的 recorded_requests 之外,recorded_manifest_shape 给出清单文档的形状(键名)。
"""

from __future__ import annotations

from repoproof.adoption.intake import tool_drafter
from repoproof.ui.services import product_jobs


def test_the_verifier_rules_spell_out_the_manifest_document() -> None:
    text = tool_drafter._OPEN_API_VERIFIER_RULES
    assert '"responses"' in text and "schema_version" in text
    for field in ("method", "host", "path", "query", "status", "content_type", "body"):
        assert field in text


def test_the_manifest_shape_is_a_named_context_fact() -> None:
    shape = product_jobs._recorded_manifest_shape()
    assert shape["schema_version"] == "int" and shape["responses"].startswith("array")
    assert "body" in shape["responses"] and "content_type" in shape["responses"]
