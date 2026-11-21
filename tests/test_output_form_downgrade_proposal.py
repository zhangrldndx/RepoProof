"""闭包外的运行期资源不是修复得掉的缺陷——要提降级(m6.4 prework 8b)。

上游有些渲染器只会写出引用 CDN 脚本/在线瓦片的页面。结构闸门以
WORKSPACE_HTML_EXTERNAL_RESOURCE 判死是对的(交付不许运行期联网),但把它交给生产者
反复修复是白花:上游没有离线渲染路径时,任何生产者都写不出通过的页面。自检终态要把
这一类失败转成给用户的**交付形态降级提案**,而不是一句"人工复核公开合同"。

不变量:
  I1 终轮诊断含 WORKSPACE_HTML_EXTERNAL_RESOURCE → 结果与耐久报告的 recommended_action 含三条降级选项,
     并点名被引用的外部资源;
  I2 结果带 downgrade_proposal 结构化字段(kind=OUTPUT_FORM,codes);
  I3 与外部资源无关的失败不出现降级提案。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from repoproof.adoption.intake.draft_selfcheck import (
    DraftSelfCheckRoundV1,
    output_form_downgrade_proposal,
    read_draft_self_check,
)
from repoproof.ui.services import product_jobs


def test_the_proposal_names_the_resource_and_three_options() -> None:
    proposal = output_form_downgrade_proposal(
        (
            "WORKSPACE_REFERENCE_CONTRACT_FAILED",
            "WORKSPACE_HTML_EXTERNAL_RESOURCE: https://cdn.example.net/lib.min.js (+2 more)",
        )
    )
    assert proposal is not None
    assert proposal["kind"] == "OUTPUT_FORM"
    assert "cdn.example.net" in proposal["text"]
    assert proposal["text"].count("①") == 1 and "②" in proposal["text"] and "③" in proposal["text"]


def test_unrelated_failures_get_no_proposal() -> None:
    assert output_form_downgrade_proposal(("WORKSPACE_REFERENCE_EXECUTION_FAILED", "KeyError: 'x'")) is None


def _ready():
    return SimpleNamespace(
        compatible=True, current=True, ready=False, ready_to_confirm=True,
        reason_codes=[], recommended_action="", model_dump=lambda mode: {},
    )


def test_the_self_check_terminal_carries_the_proposal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        product_jobs,
        "_self_check_round",
        lambda *_a, **kw: DraftSelfCheckRoundV1(
            round=kw.get("round_index", 1),
            check_ok=False,
            reason_codes=("WORKSPACE_REFERENCE_CONTRACT_FAILED",),
            diagnostics=(
                "WORKSPACE_HTML_EXTERNAL_RESOURCE",
                "WORKSPACE_HTML_EXTERNAL_RESOURCE: https://tiles.example.org/{z}/{x}/{y}.png",
            ),
        ),
    )
    monkeypatch.setattr(product_jobs, "_pinned_upstream_supply_verdict", lambda *_a, **_k: None)
    monkeypatch.setattr(product_jobs, "_core_draft_readiness", lambda *_a, **_k: _ready())
    monkeypatch.setattr(product_jobs, "_validated_draft_dir", lambda *a, **k: (tmp_path, ""))
    (tmp_path / "draft.yaml").write_text("tool:\n  delivery_profile_id: workspace_bundle_v1\n", encoding="utf-8")
    monkeypatch.setattr("repoproof.adoption.intake.draft_selfcheck.is_workspace_draft", lambda _d: True)

    result = product_jobs.run_draft_self_check(tmp_path, repair=False, drafter=None)

    assert result["status"] == "FAILED"
    assert "tiles.example.org" in result["recommended_action"]
    assert result["downgrade_proposal"]["kind"] == "OUTPUT_FORM"
    durable = read_draft_self_check(tmp_path)
    assert durable is not None and "tiles.example.org" in durable.recommended_action
