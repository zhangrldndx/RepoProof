"""新鲜探针场景失败时也要记住(incident-fresh-probe-scenarios-not-remembered-on-failure-*)。

H20 的不变量是「一次自检内新鲜探针只向模型提案一次」,但落盘只在提案*通过*时发生——而需要
稳定证据的恰恰是失败的那些轮:d6(altair)八轮分歧,每轮的货币都不一样(SEK→EUR→JPY→GBP),
草稿蓝图里根本没有 SEK;失败原话每轮都变,停滞预算与无效主人检测再次被躲过,
fresh_probe_blueprints.json 从未写出。

不变量:
  I1 新鲜探针的提案结果无论通过与否都带 blueprints(模型提案之后的任何失败都带);
  I2 自检首轮把提案记入 fresh_probe_blueprints.json,即使该轮探针失败;
  I3 后续轮以同一组场景调用(fresh_scenarios=记住的那组),不再向模型提案。
"""

from __future__ import annotations

import json
from pathlib import Path

from repoproof.ui.services import product_jobs

_ROW = {"blueprint_id": "fresh-1", "title": "t", "scenario": "s", "input_kind": "directory", "parameters": {"k": 1}}


def _draft() -> dict:
    return {
        "tool": {
            "delivery_profile_id": "workspace_bundle_v1",
            "delivery_requirements": {"network": "offline"},
            "workspace_contract": {"open_api_hosts": []},
        },
        "_delivery_profile": {"profile_id": "workspace_bundle_v1"},
    }


def test_a_failing_fresh_probe_still_pins_its_scenarios(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [_ROW]}))
    calls: list[dict] = []

    def fake(draft_dir, *, n, offline, fresh_scenarios=None, **_kw):
        calls.append({"offline": offline, "fresh_scenarios": fresh_scenarios})
        return {
            "ok": False,
            "failure_owner": "CONTRACT",
            "reason_codes": ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
            "diagnostics": ["ALERT_STATUS_MISMATCH"],
            "blueprints": [_ROW],
        }

    monkeypatch.setattr(product_jobs, "propose_workspace_fixture_candidates", fake)
    first = product_jobs._self_check_round(tmp_path, _draft(), round_index=1)
    assert first.check_ok is False
    assert (tmp_path / product_jobs._FRESH_PROBE_FILENAME).is_file(), "the failed proposal must be pinned"
    assert product_jobs._fresh_probe_scenarios(tmp_path) == [_ROW]
    product_jobs._self_check_round(tmp_path, _draft(), round_index=2)
    assert calls[0]["fresh_scenarios"] is None
    assert calls[1]["fresh_scenarios"] == [_ROW]
