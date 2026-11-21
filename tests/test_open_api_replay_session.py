"""开放 API 工具的每一次受管运行都经同一个会话(m6.4 prework 8c)。

密封自检、冻结后验收、ACTIVE 后的新鲜审核——三处运行开放 API 工具,规则只能有一份:
藏掉录制、指桩、种金丝雀、事后按台账裁决。

不变量:
  I1 输入带 __responses__ → 工具看到的视图里没有它、环境含基址映射与金丝雀、桩在跑;
  I2 事后裁决:未录制请求 / 金丝雀进请求 / 金丝雀进制品 / 一次都没调 → 各自的公开码;
     守规矩 → 无码;
  I3 输入不带 __responses__ → 视图就是原输入、环境为空、无桩、裁决为空(离线工具一字不差);
  I4 会话结束后桩已停,临时视图不留在原输入旁。
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from repoproof.execution import open_api_replay
from repoproof.execution.open_api_replay import replay_session

_HOST = "api.example.org"


def _input(tmp_path: Path, *, recorded: bool) -> Path:
    source = tmp_path / "input"
    source.mkdir()
    (source / "data.json").write_text("{}", encoding="utf-8")
    if recorded:
        responses = source / open_api_replay.RESPONSES_DIRNAME
        responses.mkdir()
        (responses / "r.json").write_text(json.dumps({"items": [1]}), encoding="utf-8")
        open_api_replay.write_manifest(
            responses,
            [{"method": "GET", "host": _HOST, "path": "/v1/items", "query": "", "status": 200,
              "content_type": "application/json", "body": "r.json"}],
        )
    return source


def test_a_recorded_input_is_hidden_and_stubbed(tmp_path: Path) -> None:
    source = _input(tmp_path, recorded=True)
    with replay_session(source, hosts=(_HOST,), stage_dir=tmp_path / "stage") as session:
        assert session.server is not None
        assert not (session.tool_input / open_api_replay.RESPONSES_DIRNAME).exists()
        assert (session.tool_input / "data.json").is_file()
        bases = json.loads(session.env[open_api_replay.BASE_URLS_ENV])
        assert bases[_HOST].startswith("http://127.0.0.1:")
        assert session.env[open_api_replay.CANARY_ENV]
        with urllib.request.urlopen(bases[_HOST] + "/v1/items") as response:
            assert json.load(response) == {"items": [1]}
        artifact = tmp_path / "artifact"
        artifact.mkdir()
        (artifact / "README.md").write_text("fine", encoding="utf-8")
        assert session.verdict(artifact) == []
    assert not session.tool_input.exists()


def test_each_violation_has_its_code(tmp_path: Path) -> None:
    source = _input(tmp_path, recorded=True)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "README.md").write_text("fine", encoding="utf-8")
    with replay_session(source, hosts=(_HOST,), stage_dir=tmp_path / "s1") as session:
        assert [row for row in session.verdict(artifact)] == ["WORKSPACE_REFERENCE_NO_API_CALLS"]
    with replay_session(source, hosts=(_HOST,), stage_dir=tmp_path / "s2") as session:
        base = json.loads(session.env[open_api_replay.BASE_URLS_ENV])[_HOST]
        try:
            urllib.request.urlopen(base + "/v1/other")
        except urllib.error.HTTPError:
            pass
        assert "WORKSPACE_REFERENCE_UNRECORDED_REQUEST" in session.verdict(artifact)
    with replay_session(source, hosts=(_HOST,), stage_dir=tmp_path / "s3") as session:
        base = json.loads(session.env[open_api_replay.BASE_URLS_ENV])[_HOST]
        urllib.request.urlopen(base + "/v1/items")
        leaked = tmp_path / "leaked"
        leaked.mkdir()
        (leaked / "README.md").write_text(session.env[open_api_replay.CANARY_ENV], encoding="utf-8")
        assert "WORKSPACE_REFERENCE_CREDENTIAL_LEAK" in session.verdict(leaked)


def test_an_offline_input_passes_through_untouched(tmp_path: Path) -> None:
    source = _input(tmp_path, recorded=False)
    with replay_session(source, hosts=(), stage_dir=tmp_path / "stage") as session:
        assert session.server is None and session.tool_input == source and session.env == {}
        assert session.verdict(tmp_path) == []
