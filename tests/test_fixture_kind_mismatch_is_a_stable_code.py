"""夹具候选生成的失败要有稳定、可路由的公开码(incident-public-code-is-exception-text-*)。

两起事故同一处投影:code = getattr(exc,'code') or str(exc) or 类名。ValidationError 没有
.code → 整段 pydantic 报文成了公开码(m6.4);DraftError 报文为空 → 类名 'DRAFTERROR' 成了公开码
(m6.3)。不稳定的码路由不到主人,旅程在第 1 轮零修复终止;报文本身又该保留在诊断里。

不变量:
  I1 构建器写出与蓝图 kind 不符的夹具 → FixtureBuilderError,码 FIXTURE_BUILDER_OUTPUT_KIND_MISMATCH,
     detail 说出期望与实得的 kind;
  I2 投影函数:FixtureBuilderError 取其 code;ValidationError → FIXTURE_CANDIDATE_INVALID;其他异常 →
     FIXTURE_CANDIDATE_GENERATION_FAILED;报文与类名一律进 diagnostics,不进 code;
  I3 FIXTURE_BUILDER_OUTPUT_KIND_MISMATCH 路由到构建器修复。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from repoproof.adoption.intake.draft_selfcheck import repair_target_for
from repoproof.adoption.intake.workspace_fixtures import (
    FixtureBlueprintV1,
    FixtureBuilderError,
    InputFixtureCandidateV1,
    build_fixture_candidate,
)
from repoproof.ui.services import product_jobs


def test_a_directory_for_a_file_blueprint_is_a_stable_builder_code(tmp_path: Path) -> None:
    builder = tmp_path / "fixture_builder.py"
    builder.write_text(
        "import os\n"
        "def build(blueprint, output_path):\n"
        "    os.makedirs(output_path)\n"
        "    open(os.path.join(output_path, 'config.json'), 'w').write('{}')\n",
        encoding="utf-8",
    )
    blueprint = FixtureBlueprintV1(blueprint_id="b1", title="t", scenario="s", input_kind="file", parameters={"k": 1})
    with pytest.raises(FixtureBuilderError) as caught:
        build_fixture_candidate(
            blueprint=blueprint, builder_id="anon-builder", builder_source=builder,
            fixture_root=tmp_path / "fixtures", python_exe=sys.executable, isolation_required=False,
        )
    assert caught.value.code == "FIXTURE_BUILDER_OUTPUT_KIND_MISMATCH"
    assert "file" in caught.value.detail and "directory" in caught.value.detail


def test_projection_never_uses_exception_text_as_a_code() -> None:
    try:
        InputFixtureCandidateV1.model_validate({})
    except ValidationError as exc:
        code, diagnostics = product_jobs._workspace_fixture_public_code(exc)
    assert code == "FIXTURE_CANDIDATE_INVALID"
    assert diagnostics and "validation error" in diagnostics[0].lower()
    code, diagnostics = product_jobs._workspace_fixture_public_code(FixtureBuilderError("FIXTURE_BUILDER_FAILED", "x"))
    assert code == "FIXTURE_BUILDER_FAILED"
    code, diagnostics = product_jobs._workspace_fixture_public_code(RuntimeError(""))
    assert code == "FIXTURE_CANDIDATE_GENERATION_FAILED" and "RuntimeError" in diagnostics[0]
    for code, _ in (
        product_jobs._workspace_fixture_public_code(ValueError("a long message with spaces")),
    ):
        assert " " not in code and "\n" not in code


def test_the_kind_mismatch_is_routed_to_the_builder() -> None:
    assert repair_target_for("FIXTURE_BUILDER_OUTPUT_KIND_MISMATCH", round_index=1) == "builder"
