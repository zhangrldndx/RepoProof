"""开放 API 的主机必须是真实公共主机,占位域名在起草站就拒(incident-placeholder-host-reaches-rehearsal-*)。

d5(ebooklib)attempt-6:草稿把第二个源写成 www.example-feeds.test(保留 TLD 的占位名)并声明为 open_api 主机;
自检全过(回放桩什么都能录),彩排才报 HOST_UNREACHABLE,提案却让用户「确认本机网络」——一个静态可判的事实
走到了最后一站还被误判成可用性问题。

不变量:
  I1 保留/占位域名(.test/.example/.invalid/.localhost、example.com|net|org 及其子域、localhost、IP 字面量、无点主机)
     → OPEN_API_HOST_PLACEHOLDER 投影错误,loc 指向 workspace_contract.open_api_hosts[i];
  I2 真实主机放行;非 open_api 网络模式不检查;
  I3 is_placeholder_host 是纯函数,大小写不敏感。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    _reject_placeholder_open_api_hosts,
    is_placeholder_host,
    public_validation_diagnostics,
)


def test_placeholder_hosts_are_recognised() -> None:
    for host in ("www.example-feeds.test", "feeds.example.com", "EXAMPLE.org", "api.invalid", "localhost",
                 "svc.localhost", "127.0.0.1", "[::1]", "10.0.0.8", "nodot"):
        assert is_placeholder_host(host), host
    for host in ("export.arxiv.org", "hnrss.org", "api.open-meteo.com", "example-tools.io", "testing.dev"):
        assert not is_placeholder_host(host), host


def test_a_placeholder_host_is_a_projection_error() -> None:
    contract = {"open_api_hosts": ["export.arxiv.org", "www.example-feeds.test"]}
    with pytest.raises(DraftProjectionError) as caught:
        _reject_placeholder_open_api_hosts({"network": "open_api"}, contract)
    assert str(caught.value) == "tool-draft:OPEN_API_HOST_PLACEHOLDER"
    rows = public_validation_diagnostics(caught.value)
    assert rows[0]["loc"] == "workspace_contract.open_api_hosts.1"
    assert "www.example-feeds.test" in rows[0]["msg"]


def test_real_hosts_and_other_modes_pass() -> None:
    _reject_placeholder_open_api_hosts({"network": "open_api"}, {"open_api_hosts": ["export.arxiv.org", "hnrss.org"]})
    _reject_placeholder_open_api_hosts({"network": "none"}, {"open_api_hosts": ["www.example-feeds.test"]})
    _reject_placeholder_open_api_hosts({"network": "open_api"}, {})
