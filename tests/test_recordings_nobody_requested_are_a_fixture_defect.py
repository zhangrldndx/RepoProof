"""生产者从不请求的录制不是证据,是夹具缺陷(incident-recording-nobody-requested-becomes-the-judges-truth-*)。

d9(rich)attempt-11:鲜审场景录了 OSV /v1/vulns/GHSA-8q59… 的响应体,但 PyPI 体里没有让生产者发现这个 id 的
vulnerabilities 字段——生产者永远不会请求它;判官却「从录制体重算」,把这条录制当成真相,九轮 VULN_LIST_MISMATCH
判官/生产者/合同/构建器都修过,原话不变。请求与录制要双向一致:未录的请求早已是 UNRECORDED_REQUEST,
没人请求的录制此前无人过问。

不变量:
  I1 unused_recording_keys(manifest_rows, ledger_rows):录制了、但回放台账里从未被请求的键(规范化后比较);
  I2 生产者成功跑完后仍有未被请求的录制 → WORKSPACE_REFERENCE_UNUSED_RECORDING(诊断列出键与教学);
  I3 路由:构建器先修(它录的),生产者交替;它是输入争议(修复带摘录)。
"""

from __future__ import annotations

from repoproof.adoption.intake import draft_selfcheck
from repoproof.execution.open_api_replay import unused_recording_keys
from repoproof.ui.services import product_jobs


def _row(host: str, path: str, query: str = "", method: str = "GET") -> dict:
    return {"method": method, "host": host, "path": path, "query": query, "status": 200, "body": "b.json"}


def test_unrequested_recordings_are_named() -> None:
    manifest = [
        _row("index.example-api.dev", "/pypi/pyyaml/json"),
        _row("vulns.example-api.dev", "/v1/vulns/GHSA-1"),
        _row("index.example-api.dev", "/pypi/six/json", "b=2&a=1"),
    ]
    ledger = [
        {"method": "GET", "host": "index.example-api.dev", "path": "/pypi/pyyaml/json", "query": ""},
        {"method": "GET", "host": "INDEX.example-api.dev", "path": "/pypi/six/json", "query": "a=1&b=2"},
    ]
    assert unused_recording_keys(manifest, ledger) == ["GET vulns.example-api.dev/v1/vulns/GHSA-1"]
    assert unused_recording_keys(manifest, manifest) == []
    assert unused_recording_keys([], ledger) == []


def test_the_code_is_routed_and_is_an_input_dispute() -> None:
    targets = [
        draft_selfcheck.repair_target_for("WORKSPACE_REFERENCE_UNUSED_RECORDING", round_index=i) for i in range(1, 5)
    ]
    assert targets == ["builder", "reference", "builder", "reference"]
    assert "WORKSPACE_REFERENCE_UNUSED_RECORDING" in product_jobs._INPUT_DISPUTE_CODES
    assert product_jobs._workspace_fixture_failure_owner("WORKSPACE_REFERENCE_UNUSED_RECORDING") == "CONTRACT"
