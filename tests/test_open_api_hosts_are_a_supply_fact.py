"""开放 API 草稿的主机表是供给事实,起草时就要说、自检前就要查(incident-open-api-hosts-empty-selfcheck-blind-*)。

d3(fpdf2,订阅链接合成日历墙):模型把 network 起草成 open_api 却把 open_api_hosts 留空
(主机来自用户配置)。投影放行;自检五轮,生产者在密封运行里回退到真实主机、DNS 失败,
五轮同一句 URLError 全部路由给生产者,停滞检测到第五轮才停;readiness 本会在冻结时以
OPEN_API_HOSTS_MISSING 拒绝——闸门要杀的先教,且失败要说出在哪。

不变量:
  I1 投影:network=open_api 且 open_api_hosts 为空 → OPEN_API_HOSTS_MISSING(可修的表示错误);
     声明了主机通过;离线不查;修复指引写明该码怎么修;起草规则教「主机来自用户配置也要声明」;
  I2 自检:open_api 草稿主机为空 → 首轮不跑任何生产者/模型,直接以 OPEN_API_HOSTS_MISSING 定位;
  I3 路由:OPEN_API_HOSTS_MISSING 归合同;owner 投影为 CONTRACT;
  I4 主机非空或离线草稿:自检入口不受影响。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.adoption.intake import draft_selfcheck, tool_drafter
from repoproof.ui.services import product_jobs


def test_open_api_without_hosts_is_a_repairable_projection_error() -> None:
    raw = {"network": "open_api"}
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter._reject_open_api_without_hosts(raw, {"open_api_hosts": []})
    assert tool_drafter._projection_rejection_signature(caught.value) == (
        "OPEN_API_HOSTS_MISSING",
        "workspace_contract.open_api_hosts",
    )
    tool_drafter._reject_open_api_without_hosts(raw, {"open_api_hosts": ["api.example.org"]})
    tool_drafter._reject_open_api_without_hosts({"network": "offline"}, {"open_api_hosts": []})
    assert "OPEN_API_HOSTS_MISSING" in tool_drafter._PROJECTION_REPAIR_INSTRUCTION
    assert "never empty" in tool_drafter._OPEN_API_DRAFT_RULES


def _draft(*, network: str, hosts: list[str]) -> dict:
    return {
        "tool": {
            "delivery_profile_id": "open_api_workspace_v1" if network == "open_api" else "workspace_bundle_v1",
            "delivery_requirements": {"network": network},
            "workspace_contract": {"open_api_hosts": hosts},
        }
    }


def test_the_self_check_locates_missing_hosts_before_any_producer_runs(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": []}))

    def never(*_a, **_k):
        raise AssertionError("no producer, judge or model call may run before the supply fact is checked")

    monkeypatch.setattr(product_jobs, "propose_workspace_fixture_candidates", never)
    monkeypatch.setattr(product_jobs, "_probe_draft_verifier_discrimination", never)
    round_ = product_jobs._self_check_round(tmp_path, _draft(network="open_api", hosts=[]), round_index=1)
    assert round_.check_ok is False
    assert round_.reason_codes == ("OPEN_API_HOSTS_MISSING",)
    assert any("open_api_hosts" in item for item in round_.diagnostics)


def test_hosts_present_or_offline_do_not_trip_the_supply_check() -> None:
    assert product_jobs._open_api_hosts_gap(_draft(network="open_api", hosts=["api.example.org"])) is None
    assert product_jobs._open_api_hosts_gap(_draft(network="offline", hosts=[])) is None
    assert product_jobs._open_api_hosts_gap(_draft(network="open_api", hosts=[])) is not None


def test_missing_hosts_are_the_contracts_to_repair() -> None:
    assert draft_selfcheck.repair_target_for("OPEN_API_HOSTS_MISSING", round_index=1) == "contract"
    assert draft_selfcheck.repair_target_for("OPEN_API_HOSTS_MISSING", round_index=3) == "contract"
    assert product_jobs._workspace_fixture_failure_owner("OPEN_API_HOSTS_MISSING") == "CONTRACT"
