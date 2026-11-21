"""未录制请求是生产者与构建器之间的分歧,不是生产者单方的缺陷(incident-unrecorded-request-routed-only-to-producer-*)。

一趟开放 API 自检七轮:生产者按配置构造 URL(getAuthorFeed?actor=…&limit=50 …),构建器录的是
别的键;桩回 404。生产者有时吞掉 404 走完(判 UNRECORDED_REQUEST,四条请求被逐条点名),
有时抛出(判 EXECUTION_FAILED,只剩一行 HTTPError)。同一根因两种码,而修复全部发给生产者——
它改 URL,构建器不动,永远对不上。

不变量:
  I1 桩台账里有未录制请求时,判定码是 WORKSPACE_REFERENCE_UNRECORDED_REQUEST,即便生产者因此崩溃
     (崩溃是后果),崩溃原话仍进 diagnostics;
  I2 该码交替路由:构建器先(它录制),再生产者,再构建器;
  I3 起草与构建器修复提示写明 manifest 文档形状({"schema_version":1,"responses":[…]})与
     「为点名的每条请求各录一份」的修复法。
"""

from __future__ import annotations

from repoproof.adoption.intake import tool_drafter
from repoproof.adoption.intake.draft_selfcheck import repair_target_for
from repoproof.ui.services import product_jobs


class _Ledger:
    def __init__(self, unrecorded):
        self._unrecorded = unrecorded
        self.ledger = list(unrecorded)

    def unrecorded(self):
        return list(self._unrecorded)

    def canary_leaks(self):
        return []


def test_unrecorded_requests_outrank_the_crash_they_caused() -> None:
    replay = _Ledger([{"method": "GET", "host": "api.example.org", "path": "/v1/items", "query": "limit=50"}])
    verdict = product_jobs._open_api_run_verdict(
        replay, process_failed=True, crash_words=("HTTPError: HTTP Error 404: Not Found @ impl.py:12",)
    )
    assert verdict is not None
    assert verdict.code == "WORKSPACE_REFERENCE_UNRECORDED_REQUEST"
    joined = " | ".join(verdict.diagnostics)
    assert "api.example.org/v1/items?limit=50" in joined and "HTTPError" in joined
    assert product_jobs._open_api_run_verdict(_Ledger([]), process_failed=True, crash_words=()) is None


def test_the_disagreement_alternates_builder_first() -> None:
    code = "WORKSPACE_REFERENCE_UNRECORDED_REQUEST"
    owners = [repair_target_for(code, round_index=i) for i in (1, 2, 3, 4)]
    assert owners == ["builder", "reference", "builder", "reference"]


def test_prompts_teach_the_manifest_shape_and_the_repair() -> None:
    for text in (tool_drafter._SYSTEM, tool_drafter._FIXTURE_BUILDER_REPAIR_SYSTEM):
        assert '"responses"' in text or "responses list" in text, "manifest 顶层键要写明"
    assert "WORKSPACE_REFERENCE_UNRECORDED_REQUEST" in tool_drafter._FIXTURE_BUILDER_REPAIR_SYSTEM
    assert "exactly" in tool_drafter._FIXTURE_BUILDER_REPAIR_SYSTEM.lower()
