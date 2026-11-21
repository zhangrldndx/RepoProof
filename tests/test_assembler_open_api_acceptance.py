"""装配出的验收测试要经由回放桩跑开放 API 工具(m6.4 prework 7)。

冻结后的验收(oracle/test_capability.py 与 public_tests/)是 Agent 侧唯一的真相来源。
密封自检已经在冻结前经回放桩跑过生产者;验收若仍按离线工具那样直接调工具,开放 API 工具
要么真联网(违反 network_at_test_time 禁令),要么因无网失败——两种都不是判定。

不变量(对生成的测试模块本身做端到端,工具二进制是匿名假工具):
  I1 夹具带 __responses__ → 测试启动回放桩、把 __responses__ 从工具输入里藏掉、以
     REPOPROOF_OPEN_API_BASE_URLS 指向桩;守规矩的工具通过;
  I2 请求了录制之外的路径 → 失败,消息说出那条请求;
  I3 从未调用桩 → 失败;
  I4 把金丝雀写进制品 → 失败,消息点名泄露;
  I5 夹具不带 __responses__ → 与从前一字不差:不设环境变量,不起桩;
  I6 接口测试对开放 API 工具把主机映射到死端口,永远不真联网;
  I7 声明了主机的任务,回放模块随 oracle 与 public_tests 一起装配。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

from repoproof.adoption.assembly import workspace_tool_assembler as asm
from repoproof.execution import open_api_replay

_HOST = "api.anon-feeds.dev"

_FAKE_TOOL = textwrap.dedent(
    '''\
    #!/usr/bin/env python3
    import json, os, sys, urllib.request
    from pathlib import Path
    mode = os.environ.get("FAKE_TOOL_MODE", "good")
    source, out = Path(sys.argv[1]), Path(sys.argv[3])
    if out.exists():
        sys.stderr.write("output exists\\n"); sys.exit(1)
    if (source / "__responses__").exists():
        sys.stderr.write("recordings leaked into tool input\\n"); sys.exit(3)
    bases = json.loads(os.environ.get("REPOPROOF_OPEN_API_BASE_URLS", "{}"))
    if mode == "offline":
        assert not bases, "offline fixture must not receive base urls"
        count = json.loads((source / "data.json").read_text())["count"]
    elif mode == "nocall":
        count = 2
    else:
        path = "/v1/other" if mode == "unrecorded" else "/v1/items"
        with urllib.request.urlopen(bases["__HOST__"] + path + "?limit=2") as resp:
            count = len(json.load(resp)["items"])
    out.mkdir()
    text = f"items={count}\\n"
    if mode == "leak":
        text += os.environ["REPOPROOF_CANARY_TOKEN"] + "\\n"
    (out / "README.md").write_text(text)
    '''
).replace("__HOST__", _HOST)


def _fixture(root: Path, *, recorded: bool) -> None:
    source = root / "fixtures" / "example-1" / "input"
    source.mkdir(parents=True)
    (source / "data.json").write_text(json.dumps({"count": 2}), encoding="utf-8")
    if recorded:
        responses = source / open_api_replay.RESPONSES_DIRNAME
        responses.mkdir()
        (responses / "items.json").write_text(json.dumps({"items": [1, 2]}), encoding="utf-8")
        open_api_replay.write_manifest(
            responses,
            [{"method": "GET", "host": _HOST, "path": "/v1/items", "query": "limit=2",
              "status": 200, "content_type": "application/json", "body": "items.json"}],
        )
    expected = root / "fixtures" / "example-1" / "expected"
    expected.mkdir(parents=True)
    (expected / "README.md").write_text("items=2\n", encoding="utf-8")


def _module(root: Path, *, hosts: tuple[str, ...]) -> Path:
    example = SimpleNamespace(example_id="example-1")  # _test_source reads only the id
    module = root / "test_public_contract.py"
    module.write_text(asm._test_source([example], held=False, open_api_hosts=hosts), encoding="utf-8")
    shutil.copy(Path(open_api_replay.__file__), root / "_open_api_replay.py")
    # The frozen judge sits beside the public tests: a README with the item count is the whole contract here.
    (root / "semantic_verifier.py").write_text(
        "from pathlib import Path\n\n\n"
        "def verify(input_path, artifact_path):\n"
        "    ok = (Path(artifact_path) / 'README.md').read_text(encoding='utf-8').startswith('items=')\n"
        "    return {'ok': ok, 'reason_codes': [] if ok else ['README_MISMATCH'], 'checked_commitment_ids': ['c1']}\n",
        encoding="utf-8",
    )
    tool = root / "fake-tool"
    tool.write_text(_FAKE_TOOL, encoding="utf-8")
    tool.chmod(0o755)
    return module


def _pytest(module: Path, *, mode: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "REPOPROOF_TOOL_BIN": str(module.parent / "fake-tool"), "FAKE_TOOL_MODE": mode}
    env.pop("REPOPROOF_OPEN_API_BASE_URLS", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider",
         "-o", "addopts=", str(module), "-k", "test_example_1"],
        capture_output=True, text=True, env=env, cwd=module.parent, timeout=120,
    )


def test_a_compliant_tool_passes_through_the_stub(tmp_path: Path) -> None:
    _fixture(tmp_path, recorded=True)
    result = _pytest(_module(tmp_path, hosts=(_HOST,)), mode="good")
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_unrecorded_request_fails_and_is_named(tmp_path: Path) -> None:
    _fixture(tmp_path, recorded=True)
    result = _pytest(_module(tmp_path, hosts=(_HOST,)), mode="unrecorded")
    assert result.returncode != 0
    assert "/v1/other" in result.stdout, result.stdout


def test_a_tool_that_never_calls_the_stub_fails(tmp_path: Path) -> None:
    _fixture(tmp_path, recorded=True)
    result = _pytest(_module(tmp_path, hosts=(_HOST,)), mode="nocall")
    assert result.returncode != 0
    assert "never" in result.stdout.lower(), result.stdout


def test_a_canary_in_the_artifact_fails(tmp_path: Path) -> None:
    _fixture(tmp_path, recorded=True)
    result = _pytest(_module(tmp_path, hosts=(_HOST,)), mode="leak")
    assert result.returncode != 0
    assert "canary" in result.stdout.lower(), result.stdout


def test_an_offline_fixture_runs_exactly_as_before(tmp_path: Path) -> None:
    _fixture(tmp_path, recorded=False)
    result = _pytest(_module(tmp_path, hosts=()), mode="offline")
    assert result.returncode == 0, result.stdout + result.stderr


def test_interface_tests_never_reach_the_real_host() -> None:
    text = asm._interface_test_source("example-1", open_api_hosts=(_HOST,))
    assert "REPOPROOF_OPEN_API_BASE_URLS" in text and "127.0.0.1:9" in text
    assert "REPOPROOF_OPEN_API_BASE_URLS" not in asm._interface_test_source("example-1")


def test_replay_module_ships_beside_the_tests() -> None:
    files = asm._open_api_support_files("tool-anon-v1", "fixtures/tool_skeleton_anon", (_HOST,))
    assert set(files) == {
        "oracle/tool-anon-v1/_open_api_replay.py",
        "fixtures/tool_skeleton_anon/public_tests/_open_api_replay.py",
    }
    assert all("class ReplayServer" in body for body in files.values())
    assert asm._open_api_support_files("tool-anon-v1", "fixtures/tool_skeleton_anon", ()) == {}
