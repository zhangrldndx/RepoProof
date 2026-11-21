"""语义筛查的执行失败要把判官/执行器的原话带出来(incident-semantic-screen-failure-drops-the-verifier-words-*)。

五轮 WORKSPACE_SEMANTIC_SCREEN_EXECUTION_FAILED、每轮 diagnostics 为空、判官被盲修四次——
包装处 raise WorkspaceBundleError(code) from exc 把 SemanticVerifierError 的话丢了。

不变量:
  I1 投影出的 WorkspaceBundleError 码不变,diagnostics 含异常类名与首行原话(有界);
  I2 异常自带的 diagnostics/reason_codes 一并带出;
  I3 空异常也至少留下类名。
"""

from __future__ import annotations

from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import product_jobs
from repoproof.verification.semantic_artifact import SemanticVerifierError


def test_the_verifier_words_travel_with_the_code() -> None:
    exc = SemanticVerifierError("VERIFIER_PROTOCOL_ERROR: ModuleNotFoundError: No module named 'anonlib'")
    error = product_jobs._semantic_screen_failure(exc)
    assert isinstance(error, WorkspaceBundleError)
    assert error.code == "WORKSPACE_SEMANTIC_SCREEN_EXECUTION_FAILED"
    joined = " | ".join(error.diagnostics)
    assert "SemanticVerifierError" in joined and "No module named 'anonlib'" in joined


def test_attached_diagnostics_are_kept() -> None:
    exc = SemanticVerifierError("boom")
    exc.diagnostics = ("frame: verify @ semantic_verifier.py:12",)  # type: ignore[attr-defined]
    error = product_jobs._semantic_screen_failure(exc)
    assert any("semantic_verifier.py:12" in row for row in error.diagnostics)


def test_an_empty_exception_still_names_its_class() -> None:
    error = product_jobs._semantic_screen_failure(SemanticVerifierError(""))
    assert error.diagnostics and "SemanticVerifierError" in error.diagnostics[0]
