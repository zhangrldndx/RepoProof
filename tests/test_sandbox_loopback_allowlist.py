"""密封沙箱只放行回放桩端口(m6.4 prework 3)。

实测(2026-09-05):`(deny network*)` 加一条 `(allow network-outbound (remote ip "localhost:PORT"))`
后,本机桩端口可达,本机其他端口连不上,外网连 DNS 都解析不了。这里把它钉成不变量。

不变量:
  I1 不传端口时 profile 一字不变(所有离线路径的证据不受影响);
  I2 传端口时 profile 只多一条对该端口的出站放行;
  I3 真沙箱下:桩端口可达、其他端口不可达。
"""

from __future__ import annotations

import http.server
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from repoproof.execution.offline_sandbox import offline_sandbox_argv


def test_profile_is_unchanged_without_a_port(tmp_path: Path) -> None:
    argv = offline_sandbox_argv(["/usr/bin/true"], tmp_path)
    profile = argv[2]
    assert "(deny network*)" in profile
    assert "allow network-outbound" not in profile


def test_profile_gains_exactly_one_loopback_rule(tmp_path: Path) -> None:
    profile = offline_sandbox_argv(["/usr/bin/true"], tmp_path, loopback_port=48123)[2]
    assert "(deny network*)" in profile
    assert profile.count("allow network-outbound") == 1
    assert '(remote ip "localhost:48123")' in profile


@pytest.mark.skipif(sys.platform != "darwin", reason="reviewed sandbox is darwin-only")
def test_only_the_replay_port_is_reachable(tmp_path: Path) -> None:
    class _Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

    (tmp_path / "ok.json").write_text('{"ok":true}', encoding="utf-8")
    server = socketserver.TCPServer(("127.0.0.1", 0), lambda *a, **k: _Quiet(*a, directory=str(tmp_path), **k))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        def fetch(target: int) -> int:
            argv = offline_sandbox_argv(
                ["/usr/bin/curl", "-sS", "--max-time", "3", f"http://127.0.0.1:{target}/ok.json"],
                tmp_path,
                loopback_port=port,
            )
            return subprocess.run(argv, capture_output=True, text=True, timeout=20).returncode

        assert fetch(port) == 0, "桩端口应可达"
        assert fetch(port + 1) != 0, "其他端口应被拒"
    finally:
        server.shutdown()
        server.server_close()
