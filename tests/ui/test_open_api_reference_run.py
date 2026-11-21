"""密封参考运行对开放 API 工作区的观测(m6.4 prework 4–6)。

合同声明了 open_api_hosts 的工作区,其参考实现在密封环境里跑时:桩回放夹具的
`__responses__/`,沙箱只放行桩端口,基址经 REPOPROOF_OPEN_API_BASE_URLS 覆盖,环境里
种一个金丝雀令牌。桩是观测点,四种作弊/失误各有自己的公开码。

不变量:
  I1 老实的生产者(读覆盖变量、只请求已录制路径、不碰凭证)照常通过;
  I2 直接读 input/__responses__ 而不经桩 → 看不到该目录(视图里没有)→ 执行失败;
  I3 请求了未录制路径 → WORKSPACE_REFERENCE_UNRECORDED_REQUEST,点名路径;
  I4 金丝雀出现在请求头/查询串或任何产物里 → WORKSPACE_REFERENCE_CREDENTIAL_LEAK;
  I5 一次桩请求都没有(无视覆盖直连外网,或压根没抓)→ 失败诊断里点明未观测到桩请求;
  I6 未声明 open_api_hosts 的合同走原来的离线路径,一字不变。
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from repoproof.domain.models import WorkspaceArtifactContractV1
from repoproof.execution.open_api_replay import RESPONSES_DIRNAME, write_manifest
from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import product_jobs

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="sealed sandbox is darwin-only")

_RULES = (
    {"path_pattern": "README.md", "role": "guide", "media_type": "text/markdown", "validation_profile": "text_utf8_v1"},
    {"path_pattern": "data.json", "role": "data", "media_type": "application/json", "validation_profile": "json_v1"},
)


def _contract(*hosts: str) -> WorkspaceArtifactContractV1:
    return WorkspaceArtifactContractV1(rules=_RULES, open_api_hosts=tuple(hosts))


def _fixture(tmp_path: Path, *, with_responses: bool = True) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "config.json").write_text('{"want": "items"}', encoding="utf-8")
    if with_responses:
        responses = fixture / RESPONSES_DIRNAME
        responses.mkdir()
        (responses / "r1.bin").write_bytes(b'{"items":[1,2,3]}')
        write_manifest(
            responses,
            [{"method": "GET", "host": "api.example.org", "path": "/v1/items", "query": "",
              "status": 200, "headers": {"Content-Type": "application/json"}, "body": "r1.bin"}],
        )
    return fixture


_GOOD = '''
import json, os, urllib.request
from pathlib import Path

def build_workspace(input_path: Path, output_dir: Path) -> None:
    bases = json.loads(os.environ["REPOPROOF_OPEN_API_BASE_URLS"])
    with urllib.request.urlopen(bases["api.example.org"] + "/v1/items", timeout=5) as response:
        payload = json.loads(response.read())
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data.json").write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    (output_dir / "README.md").write_text("items: " + str(len(payload["items"])) + "\\n", encoding="utf-8")
'''

_VARIANTS = {
    "reads_responses_directly": _GOOD.replace(
        'bases = json.loads(os.environ["REPOPROOF_OPEN_API_BASE_URLS"])\n    with urllib.request.urlopen(bases["api.example.org"] + "/v1/items", timeout=5) as response:\n        payload = json.loads(response.read())',  # noqa: E501 - exact substring for str.replace
        'payload = json.loads((input_path / "__responses__" / "r1.bin").read_text())',
    ),
    "unrecorded_path": _GOOD.replace('"/v1/items"', '"/v1/other"').replace(
        "payload = json.loads(response.read())", "payload = {\"items\": []}"
    ).replace("with urllib.request.urlopen(", "try:\n        urllib.request.urlopen(").replace(
        ", timeout=5) as response:", ", timeout=5)\n    except Exception:\n        pass\n    if True:"
    ),
    "writes_canary": _GOOD.replace(
        '"items: " + str(len(payload["items"])) + "\\n"',
        '"items: " + str(len(payload["items"])) + " " + os.environ.get("REPOPROOF_CANARY_TOKEN", "") + "\\n"',
    ),
    "sends_canary": _GOOD.replace(
        'urllib.request.urlopen(bases["api.example.org"] + "/v1/items", timeout=5)',
        'urllib.request.urlopen(urllib.request.Request(bases["api.example.org"] + "/v1/items", headers={"Authorization": "Bearer " + os.environ.get("REPOPROOF_CANARY_TOKEN", "")}), timeout=5)',  # noqa: E501 - exact substring for str.replace
    ),
    "ignores_override": _GOOD.replace(
        'bases["api.example.org"] + "/v1/items"', '"https://api.example.org/v1/items"'
    ),
    "never_fetches": _GOOD.replace(
        'bases = json.loads(os.environ["REPOPROOF_OPEN_API_BASE_URLS"])\n    with urllib.request.urlopen(bases["api.example.org"] + "/v1/items", timeout=5) as response:\n        payload = json.loads(response.read())',  # noqa: E501 - exact substring for str.replace
        'payload = {"items": [1, 2, 3]}',
    ),
}


def _run(tmp_path: Path, source: str, contract: WorkspaceArtifactContractV1, fixture: Path) -> dict:
    reference = tmp_path / "reference_impl.py"
    reference.write_text(textwrap.dedent(source), encoding="utf-8")
    upstream = tmp_path / "upstream"
    upstream.mkdir(exist_ok=True)
    return product_jobs._run_workspace_reference_candidate(
        reference_source=reference,
        input_path=fixture,
        expected_dir=tmp_path / "expected",
        contract=contract,
        python_exe=sys.executable,
        upstream_dir=upstream,
        timeout_s=60,
    )


def test_an_honest_producer_passes_through_the_replay(tmp_path: Path) -> None:
    result = _run(tmp_path, _GOOD, _contract("api.example.org"), _fixture(tmp_path))
    assert result["file_count"] == 2
    assert json.loads((tmp_path / "expected" / "data.json").read_text()) == {"items": [1, 2, 3]}


def test_reading_the_responses_directory_is_impossible(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceBundleError) as caught:
        _run(tmp_path, _VARIANTS["reads_responses_directly"], _contract("api.example.org"), _fixture(tmp_path))
    assert caught.value.code == "WORKSPACE_REFERENCE_EXECUTION_FAILED"
    assert "FileNotFoundError" in " ".join(str(d) for d in caught.value.diagnostics)


def test_an_unrecorded_request_is_named(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceBundleError) as caught:
        _run(tmp_path, _VARIANTS["unrecorded_path"], _contract("api.example.org"), _fixture(tmp_path))
    assert caught.value.code == "WORKSPACE_REFERENCE_UNRECORDED_REQUEST"
    assert "/v1/other" in " ".join(str(d) for d in caught.value.diagnostics)


@pytest.mark.parametrize("variant", ["writes_canary", "sends_canary"])
def test_a_credential_leak_is_caught(tmp_path: Path, variant: str) -> None:
    with pytest.raises(WorkspaceBundleError) as caught:
        _run(tmp_path, _VARIANTS[variant], _contract("api.example.org"), _fixture(tmp_path))
    assert caught.value.code == "WORKSPACE_REFERENCE_CREDENTIAL_LEAK"


@pytest.mark.parametrize("variant", ["ignores_override", "never_fetches"])
def test_a_producer_that_never_reaches_the_replay_is_told_so(tmp_path: Path, variant: str) -> None:
    with pytest.raises(WorkspaceBundleError) as caught:
        _run(tmp_path, _VARIANTS[variant], _contract("api.example.org"), _fixture(tmp_path))
    blob = caught.value.code + " " + " ".join(str(d) for d in caught.value.diagnostics)
    assert "OPEN_API_NO_REQUEST_OBSERVED" in blob or caught.value.code == "WORKSPACE_REFERENCE_NO_API_CALLS"
    assert "REPOPROOF_OPEN_API_BASE_URLS" in blob, "要告诉生产者该遵守哪个变量"


def test_offline_contracts_keep_the_offline_path(tmp_path: Path) -> None:
    offline = '''
from pathlib import Path
import json
def build_workspace(input_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    (output_dir / "README.md").write_text("offline\\n", encoding="utf-8")
'''
    result = _run(tmp_path, offline, _contract(), _fixture(tmp_path, with_responses=False))
    assert result["file_count"] == 2
