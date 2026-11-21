"""autopilot 代用户接受彩排边界提案一次(incident-boundary-proposal-has-no-retry-path-*)。

准入反提案已有「代用户接受一次」;彩排的实况边界(凭证/端点没了)同样是设计中的用户抉择点,
允许降级的案例里 autopilot 代用户选提案 ②:带着已知边界重新起草、重新冻结、重新彩排——只一次。

不变量:
  I1 accept_boundary_proposal=True 且提案 kind 为 PLATFORM_ACCESS/RECORDING → 第二次 tool add 带
     --known-boundaries-json(含 host/path/code),旅程继续到终点;
  I2 provenance 带 boundary_proposal_accepted_by=autopilot / boundary_original_task / boundary_codes;
  I3 第二次彩排仍是边界 → REHEARSAL_BOUNDARY,不再第三次;
  I4 不带 accept_boundary_proposal → 行为不变(REHEARSAL_BOUNDARY 终态)。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from repoproof.ui.services import autopilot

_spec = importlib.util.spec_from_file_location("_autopilot_fixtures", Path(__file__).with_name("test_autopilot.py"))
_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixtures)
_HAPPY, _Scripted, _env = _fixtures._HAPPY, _fixtures._Scripted, _fixtures._env


def _boundary_payload() -> dict:
    return {
        "ok": False,
        "verdict": "REHEARSAL_LIVE_BOUNDARY",
        "task_id": "tool-anon-tool-v1",
        "stages": {
            "rehearsal": {"verdict": "PASS_ADAPTED"},
            "live_probe": {
                "status": "LIVE_BOUNDARY",
                "reason_codes": ["PLATFORM_REQUIRES_CREDENTIALS"],
                "requests": [
                    {"host": "api.example.org", "path": "/xrpc/search", "query": "q=x", "fixture": "anchor",
                     "status": 403, "code": "PLATFORM_REQUIRES_CREDENTIALS", "detail": "HTTP 403"},
                    {"host": "api.example.org", "path": "/repos/x", "query": "", "fixture": "anchor",
                     "status": 200, "code": "OK", "detail": "HTTP 200"},
                ],
                "downgrade_proposal": {"kind": "PLATFORM_ACCESS", "codes": ["PLATFORM_REQUIRES_CREDENTIALS"],
                                       "text": "主机要求凭证;可选 ①②③"},
            },
        },
    }


class _BoundaryThenHappy:
    def __init__(self, inner, *, boundary_forever: bool = False) -> None:
        self.inner = inner
        self.builds = 0
        self.adds: list[list[str]] = []
        self.boundary_forever = boundary_forever

    def __call__(self, argv):
        argv = list(argv)
        if argv[1] == "add":
            self.adds.append(argv)
        if argv[1] == "build":
            self.builds += 1
            if self.builds == 1 or self.boundary_forever:
                self.inner.calls.append(argv)
                return _boundary_payload()
        return self.inner(argv)


def _drive(tmp_path: Path, monkeypatch, *, accept: bool, boundary_forever: bool = False):
    _state, dest = _env(tmp_path, monkeypatch)
    runner = _BoundaryThenHappy(_Scripted(tmp_path, monkeypatch, payloads=_HAPPY), boundary_forever=boundary_forever)
    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="watch the thing",
        project_root=tmp_path,
        dest_root=dest,
        runner=runner,
        record_dir=tmp_path / "record",
        accept_boundary_proposal=accept,
    )
    return result, runner


def test_the_proposal_is_accepted_once_and_the_journey_completes(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch, accept=True)
    assert result["ok"] is True and result["status"] == "ACTIVE", result["status"]
    assert len(runner.adds) == 2
    second = runner.adds[1]
    rows = json.loads(second[second.index("--known-boundaries-json") + 1])
    assert [(r["host"], r["path"], r["code"]) for r in rows] == [
        ("api.example.org", "/xrpc/search", "PLATFORM_REQUIRES_CREDENTIALS")
    ]
    provenance = result["report"]["provenance"]
    assert provenance["boundary_proposal_accepted_by"] == "autopilot"
    assert provenance["boundary_original_task"] == "tool-anon-tool-v1"
    assert provenance["boundary_codes"] == "PLATFORM_REQUIRES_CREDENTIALS"
    rehearsals = [s for s in result["report"]["stages"] if s["stage"] == "rehearsal"]
    assert [s["ok"] for s in rehearsals] == [False, True]


def test_a_second_boundary_ends_the_journey(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch, accept=True, boundary_forever=True)
    assert result["ok"] is False and result["status"] == "REHEARSAL_BOUNDARY"
    assert len(runner.adds) == 2 and runner.builds == 2


def test_without_acceptance_the_boundary_stays_terminal(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch, accept=False)
    assert result["ok"] is False and result["status"] == "REHEARSAL_BOUNDARY"
    assert len(runner.adds) == 1


# ---- 第二起(同案复跑):反提案之后的边界重起把边界弄丢了 ----
# 题面先被准入改写(NEED_REFRAME → 改写题面),彩排边界后重起时,第一次 tool add 带着边界、
# 用原题面 → 再次 NEED_REFRAME → 反提案分支的第二次 tool add 用改写题面却**不带**边界;
# 同时第二轮的 stages/draft.json 盖掉了第一轮的原件。
#   I5 重起用已接受的改写题面,且带 --known-boundaries-json;不再重问准入;
#   I6 第二轮各站 payload 另存(draft-redraft1.json …),第一轮原件不被覆盖。

_ORIGINAL = "watch someone on the paid platform"
_REFRAMED = "watch someone on the public platforms"


class _ReframeThenBoundaryThenHappy(_BoundaryThenHappy):
    def __call__(self, argv):
        argv = list(argv)
        if argv[1] == "add":
            capability = argv[argv.index("--capability") + 1]
            if capability == _ORIGINAL:
                self.adds.append(argv)
                self.inner.calls.append(argv)
                return {
                    "ok": False,
                    "admission": {"status": "NEED_REFRAME", "reason_codes": ["PLATFORM_ACCESS_PAID_CREDENTIALS"],
                                  "blockers": [], "questions": ["paid; use public?"],
                                  "reframed_capability": _REFRAMED},
                }
        return super().__call__(argv)


def test_the_redraft_keeps_the_reframe_and_the_boundary(tmp_path: Path, monkeypatch) -> None:
    _state, dest = _env(tmp_path, monkeypatch)
    runner = _ReframeThenBoundaryThenHappy(_Scripted(tmp_path, monkeypatch, payloads=_HAPPY))
    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon", capability=_ORIGINAL, project_root=tmp_path, dest_root=dest,
        runner=runner, record_dir=tmp_path / "record", accept_boundary_proposal=True,
    )
    assert result["ok"] is True and result["status"] == "ACTIVE", result["status"]
    capabilities = [a[a.index("--capability") + 1] for a in runner.adds]
    assert capabilities == [_ORIGINAL, _REFRAMED, _REFRAMED], capabilities
    redraft = runner.adds[2]
    assert "--known-boundaries-json" in redraft
    rows = json.loads(redraft[redraft.index("--known-boundaries-json") + 1])
    assert rows[0]["path"] == "/xrpc/search"
    stages = sorted(p.name for p in (tmp_path / "record" / "stages").iterdir())
    assert "draft.json" in stages and "rehearsal.json" in stages
    assert "draft-redraft1.json" in stages and "rehearsal-redraft1.json" in stages
