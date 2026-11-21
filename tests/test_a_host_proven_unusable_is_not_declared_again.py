"""一个主机被证实只有墙、从未答过 200,下一次起草不得再声明它(incident-endpoint-guessing-on-a-proven-unusable-host-*)。

d9(rich)attempt-9:已知 api.osv.dev 的 /v1/vulns(404)、/v1/query(405)是墙,起草者又发明 /v1/vulns-by-package,
撞墙后再发明 /v1/query-by-version——每猜一次花一整趟旅程(起草→自检→冻结→彩排)。同一批探针里 pypi.org 每次都
答 200。Harness 手里有「哪些主机答过、哪些主机只撞过墙」的事实,却没在起草站说出来。

不变量:
  I1 known_boundaries 也带 OK 行(彩排里答 200 的键);阻断类过滤照旧只看墙;
  I2 声明的主机若有 ≥2 条不同路径的墙且没有任何 OK 行 → OPEN_API_HOST_PROVEN_UNUSABLE 投影错误,
     loc 指到该主机,消息列出墙与「答过 200 的主机」;
  I3 有 OK 行的主机、只有一堵墙的主机、非 open_api 模式 → 放行。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    _reject_host_proven_unusable,
    public_validation_diagnostics,
)

_spec = importlib.util.spec_from_file_location(
    "_qual_driver", Path(__file__).resolve().parents[1] / "scripts" / "run_qualification_autopilot.py"
)
driver = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(driver)


def _wall(host: str, path: str, code: str = "ENDPOINT_GONE") -> dict:
    return {"host": host, "path": path, "query": "", "code": code, "detail": "HTTP 404"}


def _ok(host: str, path: str) -> dict:
    return {"host": host, "path": path, "query": "", "code": "OK", "detail": "HTTP 200"}


def test_two_walls_and_no_success_refuse_the_host() -> None:
    facts = [
        _wall("vulns.example-api.dev", "/v1/vulns"),
        _wall("vulns.example-api.dev", "/v1/query", "METHOD_NOT_ALLOWED"),
        _ok("index.example-api.dev", "/pypi/a/json"),
    ]
    contract = {"open_api_hosts": ["index.example-api.dev", "vulns.example-api.dev"]}
    with pytest.raises(DraftProjectionError) as caught:
        _reject_host_proven_unusable({"network": "open_api"}, contract, facts)
    assert str(caught.value) == "tool-draft:OPEN_API_HOST_PROVEN_UNUSABLE"
    rows = public_validation_diagnostics(caught.value)
    assert rows[0]["loc"] == "workspace_contract.open_api_hosts.1"
    assert "/v1/vulns" in rows[0]["msg"] and "/v1/query" in rows[0]["msg"]
    assert "index.example-api.dev" in rows[0]["msg"]  # the host that did answer


def test_one_wall_or_any_success_passes() -> None:
    one = [_wall("vulns.example-api.dev", "/v1/vulns")]
    _reject_host_proven_unusable({"network": "open_api"}, {"open_api_hosts": ["vulns.example-api.dev"]}, one)
    mixed = [_wall("h.example-api.dev", "/a"), _wall("h.example-api.dev", "/b"), _ok("h.example-api.dev", "/c")]
    _reject_host_proven_unusable({"network": "open_api"}, {"open_api_hosts": ["h.example-api.dev"]}, mixed)
    two = [_wall("h.example-api.dev", "/a"), _wall("h.example-api.dev", "/b")]
    _reject_host_proven_unusable({"network": "none"}, {"open_api_hosts": ["h.example-api.dev"]}, two)
    _reject_host_proven_unusable({"network": "open_api"}, {"open_api_hosts": ["h.example-api.dev"]}, [])


def test_the_driver_also_collects_the_successes(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "attempt-1" / "stages").mkdir(parents=True)
    def probe_row(host: str, path: str, code: str, status: int) -> dict:
        return {"host": host, "path": path, "query": "", "code": code, "detail": f"HTTP {status}",
                "fixture": "f", "status": status}

    (case / "attempt-1" / "stages" / "rehearsal.json").write_text(json.dumps({"stages": {"live_probe": {"requests": [
        probe_row("vulns.example-api.dev", "/v1/vulns", "ENDPOINT_GONE", 404),
        probe_row("index.example-api.dev", "/pypi/a/json", "OK", 200),
        probe_row("index.example-api.dev", "/pypi/b/json", "RESOURCE_NOT_LIVE", 404),
    ]}}}), encoding="utf-8")
    rows = driver.prior_known_boundaries(case)
    assert [(r["host"], r["path"], r["code"]) for r in rows] == [
        ("vulns.example-api.dev", "/v1/vulns", "ENDPOINT_GONE"),
        ("index.example-api.dev", "/pypi/a/json", "OK"),
    ]
