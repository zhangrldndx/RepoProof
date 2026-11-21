"""一次自检里新鲜探针只提案一次(incident-fresh-probe-scenarios-drift-and-input-insufficient-routing-*)。

每轮都向模型重新提案场景,仓库名每轮不同,失败原话跟着变——停滞预算与无效主人检测被漂移躲过,
修复也无法与上一轮比较。证据要稳定,修复才可比较。

不变量:
  I1 首轮提案后场景被记住;后续轮读到同一组场景,不再向模型提案;
  I2 记忆绑定草稿目录,不存在时为 None;
  I3 带 fresh_scenarios 调用候选生成时不触碰在线起草器。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.ui.services import product_jobs

_ROWS = [
    {"blueprint_id": "fresh-1", "title": "t", "scenario": "s", "input_kind": "directory", "parameters": {"k": 1}},
    {"blueprint_id": "fresh-2", "title": "t", "scenario": "s", "input_kind": "directory", "parameters": {"k": 2}},
]


def test_scenarios_are_remembered_per_draft(tmp_path: Path) -> None:
    assert product_jobs._fresh_probe_scenarios(tmp_path) is None
    product_jobs._remember_fresh_probe_scenarios(tmp_path, _ROWS)
    assert product_jobs._fresh_probe_scenarios(tmp_path) == _ROWS
    assert product_jobs._fresh_probe_scenarios(tmp_path / "other") is None


def test_reused_scenarios_never_reach_the_online_drafter(monkeypatch, tmp_path: Path) -> None:
    def boom():
        raise AssertionError("online drafter must not be asked for remembered scenarios")

    monkeypatch.setattr("repoproof.adoption.intake.tool_drafter.online_drafter", boom)
    (tmp_path / "draft.yaml").write_text("tool:\n  delivery_profile_id: workspace_bundle_v1\n", encoding="utf-8")
    monkeypatch.setattr(product_jobs, "_validated_draft_dir", lambda *a, **k: (tmp_path, ""))
    result = product_jobs.propose_workspace_fixture_candidates(tmp_path, n=2, offline=False, fresh_scenarios=_ROWS)
    assert result["ok"] is False
    assert "online drafter" not in str(result)
