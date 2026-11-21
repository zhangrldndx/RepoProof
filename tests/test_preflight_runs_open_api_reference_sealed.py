"""产品预检对开放 API 参考实现也要经回放会话运行(incident-preflight-runs-open-api-reference-unsealed-*)。

自检十轮通过、冻结、wheelhouse 就绪,彩排前的预检以 REFERENCE_EXECUTION_FAILED 阻断:预检把带
__responses__ 的公开样例直接交给参考运行——没有桩、没有基址映射,参考要么真联网要么 404。
密封自检与冻结验收都走 replay_session,预检这一处没有。

不变量(匿名参考脚本,永不真联网):
  I1 样例带 __responses__ → 参考看到的输入没有录制目录、环境含基址映射与金丝雀、守规矩的参考通过,会话无码;
  I2 参考请求了录制之外的路径 → 会话码 WORKSPACE_REFERENCE_UNRECORDED_REQUEST 与点名的请求;
  I3 样例不带 __responses__ → 环境不设变量、无会话码(离线任务一字不差);
  I4 参考失败时 detail 带 stderr 尾行,不只是固定句。
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from repoproof.execution import open_api_replay
from repoproof.runner import product_preflight

_HOST = "api.anon-feeds.dev"
_REFERENCE = textwrap.dedent(
    """\
    import json, os, sys, urllib.request
    from pathlib import Path
    def build_workspace(input_path, output_dir):
        src = Path(input_path); out = Path(output_dir)
        assert not (src / "__responses__").exists(), "recordings leaked"
        bases = json.loads(os.environ.get("REPOPROOF_OPEN_API_BASE_URLS", "{}"))
        mode = (src / "mode.txt").read_text().strip()
        if mode == "offline":
            assert not bases
            count = 0
        else:
            path = "/v1/other" if mode == "unrecorded" else "/v1/items"
            with urllib.request.urlopen(bases["__HOST__"] + path + "?limit=2") as resp:
                count = len(json.load(resp)["items"])
        out.mkdir()
        (out / "README.md").write_text(f"items={count}\\n")
    """
).replace("__HOST__", _HOST)


def _example(root: Path, *, mode: str, recorded: bool) -> Path:
    source = root / "input"
    source.mkdir(parents=True)
    (source / "mode.txt").write_text(mode, encoding="utf-8")
    if recorded:
        responses = source / open_api_replay.RESPONSES_DIRNAME
        responses.mkdir()
        (responses / "items.json").write_text(json.dumps({"items": [1, 2]}), encoding="utf-8")
        open_api_replay.write_manifest(
            responses,
            [{"method": "GET", "host": _HOST, "path": "/v1/items", "query": "limit=2",
              "status": 200, "content_type": "application/json", "body": "items.json"}],
        )
    return source


def _run(tmp_path: Path, *, mode: str, recorded: bool, hosts):
    reference = tmp_path / "reference_impl.py"
    reference.write_text(_REFERENCE, encoding="utf-8")
    runner = tmp_path / "run_reference.py"
    runner.write_text(product_preflight._WORKSPACE_REFERENCE_RUNNER + "\n", encoding="utf-8")
    source = _example(tmp_path, mode=mode, recorded=recorded)
    output = tmp_path / "reference-output"
    return product_preflight._execute_workspace_reference(
        python=sys.executable, runner=runner, reference=reference, input_path=source,
        reference_output=output, open_api_hosts=hosts, stage_dir=tmp_path / "session",
    )


def test_a_recorded_example_runs_through_the_stub(tmp_path: Path) -> None:
    run = _run(tmp_path, mode="good", recorded=True, hosts=(_HOST,))
    assert run.process.returncode == 0, run.process.stderr
    assert run.session_codes == []
    assert (tmp_path / "reference-output" / "README.md").read_text() == "items=2\n"


def test_an_unrecorded_request_is_named(tmp_path: Path) -> None:
    run = _run(tmp_path, mode="unrecorded", recorded=True, hosts=(_HOST,))
    assert "WORKSPACE_REFERENCE_UNRECORDED_REQUEST" in run.session_codes
    assert any("/v1/other" in row for row in run.session_details)


def test_an_offline_example_is_untouched(tmp_path: Path) -> None:
    run = _run(tmp_path, mode="offline", recorded=False, hosts=())
    assert run.process.returncode == 0, run.process.stderr
    assert run.session_codes == [] and run.session_details == []


def test_a_failure_detail_carries_the_stderr_tail() -> None:
    detail = product_preflight._reference_failure_detail("Traceback...\nKeyError: 'items'\n")
    assert "KeyError: 'items'" in detail
