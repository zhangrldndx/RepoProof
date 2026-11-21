"""开放 API 回放桩(m6.4 prework 4)。

密封验证不能让工具真的联网,也不能靠"相信它没联网"。桩在 127.0.0.1 上回放夹具里录制
的响应,请求按 (方法, 主机, 路径, 规范化查询串) 精确匹配;未录制的请求不静默成功。
桩同时是观测点:每个请求进台账,金丝雀令牌出现在请求里即凭证泄露。

不变量:
  I1 已录制的请求按录制的状态码/头/正文回放;查询串参数顺序无关;
  I2 未录制的请求 → 404 且台账 matched=False(N5:不静默成功);
  I3 请求头或查询串里出现金丝雀 → 台账 canary_seen=True(N4);
  I4 base_urls_env 把每个白名单主机映射到桩上的 http://127.0.0.1:PORT/<host>;
  I5 桩可干净停止,端口临时分配。
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from repoproof.execution.open_api_replay import (
    BASE_URLS_ENV,
    CANARY_ENV,
    ReplayServer,
    base_urls_env,
    write_manifest,
)


def _responses(tmp_path: Path) -> Path:
    root = tmp_path / "__responses__"
    root.mkdir()
    (root / "r1.bin").write_bytes(b'{"items":[1,2,3]}')
    (root / "r2.bin").write_bytes(b"<feed/>")
    write_manifest(
        root,
        [
            {"method": "GET", "host": "api.example.org", "path": "/v1/items", "query": "b=2&a=1",
             "status": 200, "headers": {"Content-Type": "application/json"}, "body": "r1.bin"},
            {"method": "GET", "host": "feeds.example.org", "path": "/rss.xml", "query": "",
             "status": 200, "headers": {"Content-Type": "application/xml"}, "body": "r2.bin"},
        ],
    )
    return root


def _get(url: str, headers: dict | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def test_recorded_requests_replay_regardless_of_query_order(tmp_path: Path) -> None:
    with ReplayServer(_responses(tmp_path)) as server:
        status, body, headers = _get(f"{server.base_url}/api.example.org/v1/items?a=1&b=2")
        assert status == 200 and body == b'{"items":[1,2,3]}'
        assert headers.get("Content-Type") == "application/json"
        status, body, _ = _get(f"{server.base_url}/feeds.example.org/rss.xml")
        assert status == 200 and body == b"<feed/>"
    assert all(row["matched"] for row in server.ledger)
    assert len(server.ledger) == 2


def test_unrecorded_requests_are_404_and_ledgered(tmp_path: Path) -> None:
    with ReplayServer(_responses(tmp_path)) as server:
        status, body, _ = _get(f"{server.base_url}/api.example.org/v1/other")
        assert status == 404
        assert b"UNRECORDED_REQUEST" in body
    row = server.ledger[-1]
    assert row["matched"] is False and row["host"] == "api.example.org" and row["path"] == "/v1/other"
    assert server.unrecorded() == [row]


def test_canary_in_headers_or_query_is_flagged(tmp_path: Path) -> None:
    canary = "canary-9f3a2b7c4d5e6f70"
    with ReplayServer(_responses(tmp_path), canary=canary) as server:
        _get(f"{server.base_url}/feeds.example.org/rss.xml", headers={"Authorization": f"Bearer {canary}"})
        _get(f"{server.base_url}/api.example.org/v1/items?a=1&b=2&token={canary}")
        _get(f"{server.base_url}/feeds.example.org/rss.xml")
    flags = [row["canary_seen"] for row in server.ledger]
    assert flags == [True, True, False]
    assert server.canary_leaks() == server.ledger[:2]


def test_base_urls_env_maps_every_allowed_host(tmp_path: Path) -> None:
    with ReplayServer(_responses(tmp_path)) as server:
        env = base_urls_env(server, ("api.example.org", "feeds.example.org"))
        base = server.base_url
    mapping = json.loads(env[BASE_URLS_ENV])
    assert mapping == {
        "api.example.org": f"{base}/api.example.org",
        "feeds.example.org": f"{base}/feeds.example.org",
    }
    assert CANARY_ENV not in env, "金丝雀由调用方单独注入"


def test_server_stops_and_frees_its_port(tmp_path: Path) -> None:
    server = ReplayServer(_responses(tmp_path))
    server.start()
    port = server.port
    server.stop()
    import socket

    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0, "端口应已释放"
