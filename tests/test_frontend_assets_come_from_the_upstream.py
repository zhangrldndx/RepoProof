"""交付的前端库文件必须来自钉版上游;上游没有,就是交付形态的边界,提给用户降级(incident-fabricated-frontend-asset-*)。

d8(geojson 震情地图):钉版上游不带任何 JS;模型凭记忆写了一份 leaflet/leaflet.js 与 index.html,
自检的判别探针对这两个文件的任何改动都拒不了,判官被改写四次——一个凭空捏造的库文件没有任何真值可比。
协议给 D8 预设的边界正是「交互地图离线不可行→降级为 GeoJSON+静态图」,但没有任何机制把它说出来。

不变量:
  I1 assert_frontend_assets_from_upstream:交付树里 ≥1 KB 的 .js/.css 若不与钉版上游树中任一文件逐字节相同 →
     WorkspaceBundleError(FRONTEND_ASSET_NOT_FROM_UPSTREAM),diagnostics 指名文件;
     上游自带的文件(逐字节相同)通过;< 1 KB 的手写脚本通过;
  I2 该码进 output_form_downgrade_proposal(OUTPUT_FORM 类提案,文本含静态图+数据文件的选项);owner CONTRACT,不派模型修;
  I3 autopilot:自检失败且带 OUTPUT_FORM 提案、accept_boundary_proposal=True → 带 known_boundaries 重起一次
     (行 code=FRONTEND_ASSET_NOT_FROM_UPSTREAM);不带标志 → DRAFT_SELF_CHECK_FAILED 终态不变;
  I4 起草规则教:known_boundaries 里的该码 → 改交付形态为自包含静态图 + 数据文件,README 说明。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from repoproof.adoption.intake import draft_selfcheck, tool_drafter
from repoproof.adoption.intake.workspace_fixtures import assert_frontend_assets_from_upstream
from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import autopilot, product_jobs


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    upstream = tmp_path / "upstream" / "anonlib" / "static"
    upstream.mkdir(parents=True)
    (upstream / "anonlib.min.js").write_text("/* real */\n" + "x" * 3000, encoding="utf-8")
    expected = tmp_path / "expected"
    (expected / "vendor").mkdir(parents=True)
    (expected / "index.html").write_text("<html><script src='app.js'></script></html>", encoding="utf-8")
    (expected / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path / "upstream", expected


def test_a_fabricated_library_file_is_a_boundary(tmp_path: Path) -> None:
    upstream, expected = _tree(tmp_path)
    (expected / "vendor" / "maplib.js").write_text("/* from memory */\n" + "y" * 2000, encoding="utf-8")
    with pytest.raises(WorkspaceBundleError) as caught:
        assert_frontend_assets_from_upstream(expected, upstream)
    assert caught.value.code == "FRONTEND_ASSET_NOT_FROM_UPSTREAM"
    assert any("vendor/maplib.js" in row for row in caught.value.diagnostics)
    assert product_jobs._workspace_fixture_failure_owner("FRONTEND_ASSET_NOT_FROM_UPSTREAM") == "CONTRACT"
    assert draft_selfcheck.repair_target_for("FRONTEND_ASSET_NOT_FROM_UPSTREAM", round_index=1) is None


def test_upstream_shipped_and_small_scripts_pass(tmp_path: Path) -> None:
    upstream, expected = _tree(tmp_path)
    shipped = (upstream / "anonlib" / "static" / "anonlib.min.js").read_bytes()
    (expected / "vendor" / "anonlib.min.js").write_bytes(shipped)
    assert_frontend_assets_from_upstream(expected, upstream)


def test_the_proposal_and_the_rules_cover_the_code() -> None:
    proposal = draft_selfcheck.output_form_downgrade_proposal(
        ("FRONTEND_ASSET_NOT_FROM_UPSTREAM: vendor/maplib.js is not shipped by the pinned upstream",)
    )
    assert proposal and proposal["kind"] == "OUTPUT_FORM" and "SVG/PNG" in proposal["text"]
    assert "FRONTEND_ASSET_NOT_FROM_UPSTREAM" in tool_drafter._OPEN_API_DRAFT_RULES or (
        "FRONTEND_ASSET_NOT_FROM_UPSTREAM" in tool_drafter._SYSTEM
    )


def _fixtures():
    spec = importlib.util.spec_from_file_location(
        "_autopilot_fixtures", Path(__file__).parent / "ui" / "test_autopilot.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _SelfCheckProposalThenHappy:
    def __init__(self, inner) -> None:
        self.inner, self.adds = inner, []

    def __call__(self, argv):
        argv = list(argv)
        if argv[1] == "add":
            self.adds.append(argv)
            if len(self.adds) == 1:
                self.inner.calls.append(argv)
                return {
                    "ok": True,  # the CLI's tool add: the draft exists; only its self-check failed
                    "admission": {"status": "RISK_REVIEW"},
                    "draft_selfcheck": {
                        "ok": False, "status": "FAILED", "rounds": 1,
                        "final_reason_codes": ["FRONTEND_ASSET_NOT_FROM_UPSTREAM"],
                        "downgrade_proposal": {
                            "kind": "OUTPUT_FORM", "codes": ["FRONTEND_ASSET_NOT_FROM_UPSTREAM"],
                            "references": ["vendor/maplib.js"], "text": "可选降级 ② 静态图(SVG/PNG)加数据文件",
                        },
                    },
                }
        return self.inner(argv)


def _drive(tmp_path: Path, monkeypatch, *, accept: bool):
    fixtures = _fixtures()
    _state, dest = fixtures._env(tmp_path, monkeypatch)
    runner = _SelfCheckProposalThenHappy(fixtures._Scripted(tmp_path, monkeypatch, payloads=fixtures._HAPPY))
    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon", capability="map the things", project_root=tmp_path, dest_root=dest,
        runner=runner, record_dir=tmp_path / "record", accept_boundary_proposal=accept,
    )
    return result, runner


def test_a_self_check_output_form_proposal_is_accepted_once_when_allowed(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch, accept=True)
    assert result["status"] == "ACTIVE", result["status"]
    assert len(runner.adds) == 2
    second = runner.adds[1]
    rows = json.loads(second[second.index("--known-boundaries-json") + 1])
    assert rows[0]["code"] == "FRONTEND_ASSET_NOT_FROM_UPSTREAM" and rows[0]["path"] == "vendor/maplib.js"
    assert result["report"]["provenance"]["boundary_proposal_accepted_by"] == "autopilot"


def test_without_the_flag_the_self_check_proposal_stays_terminal(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch, accept=False)
    assert result["status"] == "DRAFT_SELF_CHECK_FAILED" and len(runner.adds) == 1
