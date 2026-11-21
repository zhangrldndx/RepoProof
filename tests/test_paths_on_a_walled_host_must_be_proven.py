"""有墙历史的主机上,草稿只能录已证实答过的路径族(incident-endpoint-guessing-on-a-walled-host-*)。

d9(rich)attempt-10:api.osv.dev 已有三堵墙(/v1/vulns 404、/v1/query 405、/v1/query-by-version 404)与两条答过 200 的
/v1/vulns/<id>;起草者又发明 /v1/query-affected——冻结 v7 后彩排再 404。主机答过所以 H67 不拦;可「在有墙历史的主机上
发明新路径」本身就是可静态判定的猜测。

不变量:
  I1 主机有 ≥1 堵墙时,录制的路径必须等于某条 OK 路径或与之同族(同一父路径),否则
     OPEN_API_PATH_UNPROVEN_ON_WALLED_HOST 投影错误,消息列出墙、已证实路径族与被拒路径;
  I2 无墙历史的主机任何路径放行(首次旅程由彩排去证明);OK 同族路径放行;
  I3 蓝图行与构建器代码物化出的键都受检。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    _reject_unproven_paths_on_walled_hosts,
    public_validation_diagnostics,
)

_FACTS = [
    {"host": "vulns.example-api.dev", "path": "/v1/vulns", "query": "", "code": "ENDPOINT_GONE", "detail": "HTTP 404"},
    {"host": "vulns.example-api.dev", "path": "/v1/query", "query": "", "code": "METHOD_NOT_ALLOWED",
     "detail": "HTTP 405"},
    {"host": "vulns.example-api.dev", "path": "/v1/vulns/GHSA-1", "query": "", "code": "OK", "detail": "HTTP 200"},
    {"host": "vulns.example-api.dev", "path": "/v1/vulns/GHSA-2", "query": "", "code": "OK", "detail": "HTTP 200"},
    {"host": "index.example-api.dev", "path": "/pypi/a/json", "query": "", "code": "OK", "detail": "HTTP 200"},
]


def test_an_invented_path_on_a_walled_host_is_refused() -> None:
    keys = ["GET index.example-api.dev/pypi/b/json", "GET vulns.example-api.dev/v1/query-affected?name=b"]
    with pytest.raises(DraftProjectionError) as caught:
        _reject_unproven_paths_on_walled_hosts(_FACTS, keys, loc=("fixture_builder",))
    assert str(caught.value) == "tool-draft:OPEN_API_PATH_UNPROVEN_ON_WALLED_HOST"
    rows = public_validation_diagnostics(caught.value)
    assert rows[0]["loc"] == "fixture_builder"
    msg = rows[0]["msg"]
    assert "/v1/query-affected" in msg and "/v1/vulns/" in msg and "/v1/query" in msg


def test_proven_families_and_unwalled_hosts_pass() -> None:
    # Two observations vary the last segment: that template is proven.
    _reject_unproven_paths_on_walled_hosts(
        _FACTS, ["GET vulns.example-api.dev/v1/vulns/GHSA-77"], loc=("fixture_blueprints",)
    )
    # One observation proves only itself: a sibling with a different fixed segment is a guess.
    single = [row for row in _FACTS if row["path"] != "/v1/vulns/GHSA-2"]
    _reject_unproven_paths_on_walled_hosts(single, ["GET vulns.example-api.dev/v1/vulns/GHSA-1"], loc=("x",))
    with pytest.raises(DraftProjectionError):
        _reject_unproven_paths_on_walled_hosts(
            single, ["GET vulns.example-api.dev/v1/vulns/GHSA-77"], loc=("x",)
        )
    _reject_unproven_paths_on_walled_hosts(
        _FACTS, ["GET index.example-api.dev/anything/new"], loc=("fixture_blueprints",)
    )
    _reject_unproven_paths_on_walled_hosts([], ["GET vulns.example-api.dev/v1/whatever"], loc=("fixture_blueprints",))
