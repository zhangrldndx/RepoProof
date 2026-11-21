"""同一案例前几次旅程已证实的边界要带进下一次旅程(incident-known-boundaries-forgotten-across-attempts-*)。

d1(plotly):第 9/11/12 次旅程都由 anchor 证实 Bluesky searchPosts 无凭证 403;第 14 次旅程的草稿
又用回 searchPosts——已知边界只在一次旅程内记得。用户的规则是「推荐公共 API 途径重新尝试」,
重试却把上次证实的边界忘了。

不变量:
  I1 prior_known_boundaries(case_dir):读该案例各 attempt-*/stages/rehearsal*.json 的实况探针行,
     取阻断类(PLATFORM_REQUIRES_CREDENTIALS / ENDPOINT_GONE / METHOD_NOT_ALLOWED)去重;
  I2 驱动把它们作为 --known-boundaries-json 传给 tool autopilot;autopilot 以此作为首轮草稿的已知边界;
  I3 没有前次旅程 → 空,行为不变。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_qual_driver", Path(__file__).resolve().parents[1] / "scripts" / "run_qualification_autopilot.py"
)
driver = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(driver)


def _probe(*rows: tuple[str, str, str]) -> dict:
    return {"stages": {"live_probe": {"requests": [
        {"host": host, "path": path, "query": "", "code": code, "detail": "HTTP x", "fixture": "f", "status": 403}
        for host, path, code in rows]}}}


def test_blocking_rows_from_earlier_attempts_are_collected(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "attempt-3" / "stages").mkdir(parents=True)
    (case / "attempt-5" / "stages").mkdir(parents=True)
    (case / "attempt-3" / "stages" / "rehearsal.json").write_text(json.dumps(_probe(
        ("api.example.org", "/xrpc/search", "PLATFORM_REQUIRES_CREDENTIALS"),
        ("api.example.org", "/feed", "OK"),
    )), encoding="utf-8")
    (case / "attempt-5" / "stages" / "rehearsal-redraft1.json").write_text(json.dumps(_probe(
        ("api.example.org", "/xrpc/search", "PLATFORM_REQUIRES_CREDENTIALS"),
        ("other.example.org", "/v1/query", "METHOD_NOT_ALLOWED"),
        ("other.example.org", "/v0/item", "RESPONSE_SHAPE_DRIFTED"),
    )), encoding="utf-8")
    rows = driver.prior_known_boundaries(case)
    # Successes travel too, so a later draft can tell a host that answered from
    # one that only ever walled (incident-endpoint-guessing-on-a-proven-unusable-host-*).
    assert [(r["host"], r["path"], r["code"]) for r in rows] == [
        ("api.example.org", "/xrpc/search", "PLATFORM_REQUIRES_CREDENTIALS"),
        ("api.example.org", "/feed", "OK"),
        ("other.example.org", "/v1/query", "METHOD_NOT_ALLOWED"),
    ]
    assert driver.prior_known_boundaries(tmp_path / "nothing") == []


def test_the_autopilot_seeds_its_first_draft_with_known_boundaries(tmp_path: Path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "_autopilot_fixtures", Path(__file__).parent / "ui" / "test_autopilot.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(fixtures)
    from repoproof.ui.services import autopilot

    _state, dest = fixtures._env(tmp_path, monkeypatch)
    runner = fixtures._Scripted(tmp_path, monkeypatch, payloads=fixtures._HAPPY)
    seeded = [{"host": "api.example.org", "path": "/xrpc/search", "query": "", "code": "PLATFORM_REQUIRES_CREDENTIALS",
               "detail": "HTTP 403"}]
    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon", capability="do the thing", project_root=tmp_path, dest_root=dest,
        runner=runner, record_dir=tmp_path / "record", known_boundaries=seeded,
    )
    assert result["status"] == "ACTIVE"
    add = next(c for c in runner.calls if c[1] == "add")
    assert json.loads(add[add.index("--known-boundaries-json") + 1]) == seeded
