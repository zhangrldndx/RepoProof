"""reference 的静态策略错误要说出在哪并进投影修复(incident-reference-policy-error-has-no-repair-path-*)。

d10(holidays):起草终态 INVALID_MODEL_OUTPUT:REFERENCE_BROAD_EXCEPTION_MASKING,diagnostics 为空,草稿束里
还是骨架桩。同一站的 runtime-ownership 违规早已走投影修复(loc=reference_impl:<line>),broad-except 仍是裸
DraftError:没有行号、不进投影修复循环、不留 attempts。

不变量:
  I1 reference_source_policy_diagnostics(source, function_name) 给出 loc=reference_impl:<line>、type、msg 行;
  I2 起草站的 _validate_reference_source 抛 DraftProjectionError,public_validation_diagnostics 能读出那一行;
  I3 干净的源码 → 无行;缺入口 → loc=reference_impl(整文件)。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    _validate_reference_source,
    public_validation_diagnostics,
    reference_source_policy_diagnostics,
)

_BROAD = '''from pathlib import Path


def build_workspace(input_path: Path, output_dir: Path) -> None:
    try:
        text = input_path.read_text()
    except Exception:
        text = ""
    (output_dir / "out.txt").write_text(text)
'''

_CLEAN = _BROAD.replace("except Exception:", "except OSError:")


def test_a_broad_handler_is_located() -> None:
    rows = reference_source_policy_diagnostics(_BROAD, function_name="build_workspace")
    assert rows == [{
        "loc": "reference_impl:7",
        "type": "reference_broad_exception_masking",
        "msg": rows[0]["msg"],
    }]
    assert "except Exception" in rows[0]["msg"] or "broad" in rows[0]["msg"].lower()
    assert reference_source_policy_diagnostics(_CLEAN, function_name="build_workspace") == []
    missing = reference_source_policy_diagnostics("x = 1\n", function_name="build_workspace")
    assert missing[0]["loc"] == "reference_impl" and missing[0]["type"] == "reference_build_workspace_missing"


def test_the_drafting_station_raises_a_projection_error() -> None:
    with pytest.raises(DraftProjectionError) as caught:
        _validate_reference_source(_BROAD, prefix="tool-draft", function_name="build_workspace")
    assert str(caught.value) == "tool-draft:REFERENCE_BROAD_EXCEPTION_MASKING"
    rows = public_validation_diagnostics(caught.value)
    assert rows and rows[0]["loc"] == "reference_impl.7"
    _validate_reference_source(_CLEAN, prefix="tool-draft", function_name="build_workspace")
