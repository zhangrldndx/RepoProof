"""开放 API 工作区的新失败码要有主人(m6.4 prework 4)。

不变量:
  I1 未录制请求 / 凭证泄露 / 从未请求桩 → 生产者(reference);
  I2 夹具缺 __responses__ → 构建器(builder);
  I3 既有路由一字不变。
"""

from __future__ import annotations

from repoproof.adoption.intake.draft_selfcheck import repair_target_for


def test_open_api_producer_defects_route_to_the_reference() -> None:
    for code in (
        "WORKSPACE_REFERENCE_CREDENTIAL_LEAK",
        "WORKSPACE_REFERENCE_NO_API_CALLS",
    ):
        assert repair_target_for(code, round_index=1) == "reference", code
    # An unrecorded request is a producer/builder disagreement: the builder
    # answers first, then the two alternate
    # (incident-unrecorded-request-routed-only-to-producer-*).
    assert repair_target_for("WORKSPACE_REFERENCE_UNRECORDED_REQUEST", round_index=1) == "builder"
    assert repair_target_for("WORKSPACE_REFERENCE_UNRECORDED_REQUEST", round_index=2) == "reference"


def test_missing_recordings_route_to_the_builder() -> None:
    assert repair_target_for("WORKSPACE_REFERENCE_RESPONSES_MISSING", round_index=1) == "builder"


def test_existing_routing_is_untouched() -> None:
    assert repair_target_for("WORKSPACE_REFERENCE_EXECUTION_FAILED", round_index=1) == "reference"
    assert repair_target_for("FIXTURE_BUILDER_FAILED", round_index=1) == "builder"
    assert repair_target_for("WORKSPACE_RUNTIME_WHEELHOUSE_MISSING", round_index=1) is None
