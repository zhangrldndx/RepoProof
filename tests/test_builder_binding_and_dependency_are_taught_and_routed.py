"""起草拒绝要带字段话、被拒文档要留证;生产者少依赖要教也要路由(incident-builder-binding-rejection-without-field-*,
incident-dependency-missing-unrouted-*)。

d4(open-meteo):三次投影修复都撞 FIXTURE_BLUEPRINT_PARAMETER_BINDING_MISMATCH,终态
INVALID_MODEL_OUTPUT、零诊断——这条规则不经 _projection_error,修复回合只拿到码;规则又只在 build
函数体内找 blueprint["parameters"],交给 helper 读参数的构建器一律拒;被拒的三份文档没落盘,无法取证。
d6(altair):生产者 import pandas,密封运行 ModuleNotFoundError;WORKSPACE_REFERENCE_DEPENDENCY_MISSING
owner 是 CONTRACT,路由却是 None,第 1 轮即终态;起草提示没有告诉生产者密封运行里只有什么。

不变量:
  I1 参数绑定在模块内任何函数里读 X["parameters"]/X.get("parameters") 都算;不读 → 投影错误带
     ("FIXTURE_BLUEPRINT_PARAMETER_BINDING_MISMATCH", "fixture_builder") 与说明;
  I2 INVALID_MODEL_OUTPUT 的 DraftError 带 attempts(每次的文档与拒绝),persist_draft_projection_attempts
     写进草稿束 draft_projection_attempts.json;
  I3 WORKSPACE_REFERENCE_DEPENDENCY_MISSING 路由 reference(任何轮次);
  I4 起草与修复提示都写明:生产者只能 import 标准库、钉版上游及上游自己声明的依赖。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.adoption.intake import draft_selfcheck, tool_drafter

_BUILDER_VIA_HELPER = '''
import json
from pathlib import Path

def _write(bp, out):
    params = bp["parameters"]
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "config.json").write_text(json.dumps(params))

def build(blueprint, output_path):
    _write(blueprint, output_path)
'''

_BUILDER_NO_PARAMS = '''
from pathlib import Path

def build(blueprint, output_path):
    Path(output_path).mkdir(parents=True, exist_ok=True)
    (Path(output_path) / "config.json").write_text("{}")
'''


def test_parameters_may_be_read_in_a_helper() -> None:
    tool_drafter._validate_fixture_builder_source(_BUILDER_VIA_HELPER)


def test_a_builder_that_never_reads_parameters_is_told_so() -> None:
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter._validate_fixture_builder_source(_BUILDER_NO_PARAMS)
    assert tool_drafter._projection_rejection_signature(caught.value) == (
        "FIXTURE_BLUEPRINT_PARAMETER_BINDING_MISMATCH",
        "fixture_builder",
    )
    rows = tool_drafter.public_validation_diagnostics(caught.value)
    assert rows and "parameters" in rows[0]["msg"]


def test_the_invalid_output_terminal_keeps_the_rejected_documents(tmp_path: Path) -> None:
    error = tool_drafter._projection_error("FIXTURE_BLUEPRINT_PARAMETER_BINDING_MISMATCH", ("fixture_builder",), "m")
    attempts = [{"attempt": 1, "reason_code": "FIXTURE_BLUEPRINT_PARAMETER_BINDING_MISMATCH",
                 "public_validation_errors": [{"loc": "fixture_builder", "type": "x", "msg": "m"}],
                 "document": {"fixture_builder": "def build(b, o): pass"}}]
    wrapped = tool_drafter._invalid_model_output_error(error, attempts=attempts)
    assert wrapped.attempts == attempts
    assert wrapped.diagnostics and wrapped.diagnostics[0]["loc"] == "fixture_builder"
    path = tool_drafter.persist_draft_projection_attempts(tmp_path, wrapped)
    assert path == tmp_path / "draft_projection_attempts.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["attempts"][0]["document"]["fixture_builder"].startswith("def build")


def test_a_missing_dependency_is_the_producers_to_repair() -> None:
    assert draft_selfcheck.repair_target_for("WORKSPACE_REFERENCE_DEPENDENCY_MISSING", round_index=1) == "reference"
    assert draft_selfcheck.repair_target_for("WORKSPACE_REFERENCE_DEPENDENCY_MISSING", round_index=4) == "reference"


def test_the_import_closure_is_taught_to_the_producer() -> None:
    assert "reference_impl may import only" in tool_drafter._SYSTEM
    assert "WORKSPACE_REFERENCE_DEPENDENCY_MISSING" in tool_drafter._WORKSPACE_REFERENCE_REPAIR_SYSTEM
