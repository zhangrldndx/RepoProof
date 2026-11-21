"""判官证据文档不合法要说出哪个字段,并按字段归主(incident-verifier-evidence-invalid-routed-to-builder-*)。

d3(fpdf2)attempt-5:SemanticVerifierEvidenceV2 校验失败,公开码却是 FIXTURE_CANDIDATE_INVALID
(任何 pydantic ValidationError 都映射到它),四次修复全给了构建器,诊断只有
「1 validation error for SemanticVerifierEvidenceV2」——哪个字段、什么问题,一个字没有。
这个模型混着两种字段:判官写的(passed/reason_codes/reason_details/checked_commitment_ids)
与 Harness 填的(各 sha256、upstream_commit、import_module、required_commitment_ids)。

不变量:
  I1 判官字段不合法 → WORKSPACE_SEMANTIC_VERIFIER_EVIDENCE_INVALID(owner CONTRACT,路由 verifier);
  I2 Harness 字段不合法 → WORKSPACE_SEMANTIC_EVIDENCE_RECORD_INVALID(owner HARNESS,不派模型修);
  I3 其他模型的 ValidationError 仍是 FIXTURE_CANDIDATE_INVALID;
  I4 ValidationError 的原话带字段行(loc/type/msg,不含输入值),不止第一行。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from repoproof.adoption.intake import draft_selfcheck
from repoproof.adoption.intake.workspace_fixtures import FixtureBlueprintV1
from repoproof.ui.services import product_jobs
from repoproof.verification.workspace_semantic import SemanticVerifierEvidenceV2


def _valid() -> dict:
    return {
        "verifier_id": "anon-verifier", "verifier_source_sha256": "0" * 64, "input_kind": "directory",
        "input_sha256": "0" * 64, "artifact_tree_sha256": "0" * 64, "artifact_manifest_sha256": "0" * 64,
        "workspace_contract_sha256": "0" * 64, "intent_confirmation_sha256": "0" * 64,
        "upstream_commit": "a" * 40, "import_module": "anon", "upstream_imports": 1, "upstream_calls": 1,
        "required_commitment_ids": ["c1"], "checked_commitment_ids": ["c1"], "passed": False,
        "reason_codes": [], "reason_details": {},
    }


def _error(**overrides) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        SemanticVerifierEvidenceV2.model_validate({**_valid(), **overrides})
    return caught.value


def test_a_bad_verifier_field_is_the_verifiers_defect() -> None:
    code, words = product_jobs._workspace_fixture_public_code(_error(reason_codes=["not a code!"]))
    assert code == "WORKSPACE_SEMANTIC_VERIFIER_EVIDENCE_INVALID"
    assert product_jobs._workspace_fixture_failure_owner(code) == "CONTRACT"
    assert draft_selfcheck.repair_target_for(code, round_index=1) == "verifier"
    assert draft_selfcheck.repair_target_for(code, round_index=3) == "verifier"
    assert any("reason_codes" in row for row in words), words


def test_a_bad_harness_field_is_the_harnesss_defect() -> None:
    code, words = product_jobs._workspace_fixture_public_code(_error(upstream_commit="not-a-commit"))
    assert code == "WORKSPACE_SEMANTIC_EVIDENCE_RECORD_INVALID"
    assert product_jobs._workspace_fixture_failure_owner(code) == "HARNESS"
    assert draft_selfcheck.repair_target_for(code, round_index=1) is None
    assert any("upstream_commit" in row for row in words), words


def test_other_validation_errors_keep_the_fixture_code() -> None:
    with pytest.raises(ValidationError) as caught:
        FixtureBlueprintV1.model_validate({"blueprint_id": "x"})
    code, _words = product_jobs._workspace_fixture_public_code(caught.value)
    assert code == "FIXTURE_CANDIDATE_INVALID"


def test_the_words_name_the_field_and_never_the_value() -> None:
    words = product_jobs._exception_words(_error(reason_codes=["SECRET-VALUE-XYZ"]))
    joined = " ".join(words)
    assert len(words) >= 2, words
    assert "reason_codes" in joined
    assert "SECRET-VALUE-XYZ" not in joined
