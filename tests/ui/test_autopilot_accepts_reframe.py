"""autopilot 代用户接受反提案(m6.4 prework 2)。

准入给出 NEED_REFRAME 后,旅程不能就此结束:代用户接受改写题面、重新起草,并把
「原话 → 改写 → 谁接受的」写进 provenance。改写只允许一次——改写后仍要改写就是
准入自相矛盾,记 REFRAME_LOOP;预期拒绝的负控若被改写而不是拒绝,也是失败。

不变量:
  I1 NEED_REFRAME → 记录 draft 阶段的边界事实 → 用 reframed_capability 再跑一次 tool add → 正常继续;
  I2 provenance 带 reframe_original / reframe_accepted / reframe_accepted_by=autopilot;
  I3 第二次仍 NEED_REFRAME → REFRAME_LOOP,不再第三次;
  I4 expect_admission_rejection=True 时收到 NEED_REFRAME → REFRAME_WHERE_REJECTION_EXPECTED。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from repoproof.ui.services import autopilot

_spec = importlib.util.spec_from_file_location("_autopilot_fixtures", Path(__file__).with_name("test_autopilot.py"))
_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixtures)
_HAPPY, _Scripted, _env = _fixtures._HAPPY, _fixtures._Scripted, _fixtures._env

_ORIGINAL = "帮我盯着某人在推特上的帖子，看发帖时间和内容。"
_REFRAMED = "帮我盯着某人在公共 API（Bluesky/Mastodon/GitHub/Hacker News）上的帖子，看发帖时间和内容。"


def _reframe_payload() -> dict:
    return {
        "ok": False,
        "admission": {
            "status": "NEED_REFRAME",
            "reason_codes": ["PLATFORM_ACCESS_PAID_CREDENTIALS"],
            "blockers": [],
            "questions": ["该平台读取需付费凭证；是否改用公共 API？"],
            "reframed_capability": _REFRAMED,
        },
    }


class _ReframeThenHappy:
    """First `tool add` answers NEED_REFRAME; later ones follow the scripted happy path."""

    def __init__(self, inner, *, reframe_forever: bool = False) -> None:
        self.inner = inner
        self.capabilities: list[str] = []
        self.reframe_forever = reframe_forever

    def __call__(self, argv):
        argv = list(argv)
        if argv[1] == "add":
            self.capabilities.append(argv[argv.index("--capability") + 1])
            if len(self.capabilities) == 1 or self.reframe_forever:
                self.inner.calls.append(argv)
                return _reframe_payload()
        return self.inner(argv)


def _drive(tmp_path: Path, monkeypatch, *, expect_rejection: bool = False, reframe_forever: bool = False):
    _state, dest = _env(tmp_path, monkeypatch)
    runner = _ReframeThenHappy(_Scripted(tmp_path, monkeypatch, payloads=_HAPPY), reframe_forever=reframe_forever)
    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability=_ORIGINAL,
        project_root=tmp_path,
        dest_root=dest,
        runner=runner,
        record_dir=tmp_path / "record",
        expect_admission_rejection=expect_rejection,
    )
    return result, runner


def test_reframe_is_accepted_and_the_journey_completes(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch)
    assert result["ok"] is True and result["status"] == "ACTIVE", result["status"]
    assert runner.capabilities == [_ORIGINAL, _REFRAMED]
    provenance = result["report"]["provenance"]
    assert provenance["reframe_original"] == _ORIGINAL
    assert provenance["reframe_accepted"] == _REFRAMED
    assert provenance["reframe_accepted_by"] == "autopilot"
    assert provenance["reframe_reason_codes"] == "PLATFORM_ACCESS_PAID_CREDENTIALS"
    boundary = next(s for s in result["report"]["stages"] if s["stage"] == "draft")
    assert "PLATFORM_ACCESS_PAID_CREDENTIALS" in boundary["reason_codes"]
    assert boundary["facts"]["admission_status"] == "NEED_REFRAME"


def test_a_second_reframe_is_a_loop_not_a_third_attempt(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch, reframe_forever=True)
    assert result["ok"] is False and result["status"] == "REFRAME_LOOP"
    assert len(runner.capabilities) == 2


def test_reframe_where_rejection_was_expected_is_a_failure(tmp_path: Path, monkeypatch) -> None:
    result, runner = _drive(tmp_path, monkeypatch, expect_rejection=True)
    assert result["ok"] is False and result["status"] == "REFRAME_WHERE_REJECTION_EXPECTED"
    assert len(runner.capabilities) == 1
