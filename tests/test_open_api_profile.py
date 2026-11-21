"""开放 API 工作区 profile(m6.4 prework 1)。

支持面向前推一步:交付的工具运行期可以 GET 合同白名单里的**免凭证公开主机**。这是一个
新的交付 profile,不是往 workspace_bundle_v1 里偷偷塞网络——七个已 ACTIVE 的离线工具
的证据一字不变。

不变量:
  I1 交付要求的 network 维度三值化:offline / open_api / required;open_api 选到新 profile,
     offline 仍选 workspace_bundle_v1,required 仍是 NETWORK_MODE_MISMATCH;
  I2 新 profile 的公开上下文声明 network=open_api 并附规则;起草上下文列出三个 profile;
  I3 工作区合同新增 open_api_hosts:小写主机名、无 scheme/路径、去重;默认空——
     所有已冻结合同原样可读;
  I4 cli_v2 一字不变。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from repoproof.adoption.delivery.product_profile import (
    OPEN_API_WORKSPACE_PROFILE_ID,
    WORKSPACE_BUNDLE_PROFILE_ID,
    DeliveryRequirements,
    ProductProfileError,
    product_delivery_profile,
    select_product_delivery_profile,
)
from repoproof.domain.models import WorkspaceArtifactContractV1


def _requirements(network: str) -> dict:
    return {
        "inputs": [
            {"kind": "directory", "location": "local", "representation": "utf8_text",
             "format_label": "config", "role": "抓取配置与上一次输出"}
        ],
        "outputs": [
            {"kind": "directory", "format_id": "workspace_bundle",
             "format_label": "workspace", "role": "仪表盘工作区"}
        ],
        "network": network,
        "credentials": "none",
        "lifecycle": "per_invocation",
        "runtime": "local_cpu",
        "browser": "none",
        "external_side_effects": "none",
    }


def test_open_api_network_selects_the_new_profile() -> None:
    profile = select_product_delivery_profile(_requirements("open_api"))
    assert profile.profile_id == OPEN_API_WORKSPACE_PROFILE_ID
    assert profile.network == "open_api"
    assert profile.credentials == "none" and profile.lifecycle == "per_invocation"


def test_offline_directory_still_selects_workspace_bundle() -> None:
    profile = select_product_delivery_profile(_requirements("offline"))
    assert profile.profile_id == WORKSPACE_BUNDLE_PROFILE_ID
    assert profile.network == "offline"


def test_required_network_is_still_a_mismatch() -> None:
    with pytest.raises(ProductProfileError) as caught:
        select_product_delivery_profile(_requirements("required"))
    assert "NETWORK_MODE_MISMATCH" in str(caught.value)


def test_the_requirements_model_states_all_three_values() -> None:
    for value in ("offline", "open_api", "required"):
        assert DeliveryRequirements.model_validate(_requirements(value)).network == value


def test_prompt_context_declares_open_api_and_its_rules() -> None:
    context = product_delivery_profile(OPEN_API_WORKSPACE_PROFILE_ID).prompt_context()
    assert context["network"] == "open_api"
    rules = context["open_api_rules"]
    joined = " ".join(str(v) for v in rules.values()).lower()
    assert "open_api_hosts" in joined and "get" in joined
    assert "credential" in joined or "凭证" in joined


def test_drafting_context_lists_three_profiles() -> None:
    from repoproof.adoption.intake.tool_drafter import _context_with_product_profile

    ids = [p["profile_id"] for p in _context_with_product_profile({})["product_support_profiles"]]
    assert ids == ["cli_v2", WORKSPACE_BUNDLE_PROFILE_ID, OPEN_API_WORKSPACE_PROFILE_ID]


def test_cli_v2_is_untouched() -> None:
    profile = product_delivery_profile("cli_v2")
    assert profile.network == "offline" and profile.output_kind == "stdout"


_RULE = {
    "path_pattern": "README.md",
    "role": "human documentation",
    "media_type": "text/markdown",
    "validation_profile": "text_utf8_v1",
}


def test_contract_accepts_normalised_hosts() -> None:
    contract = WorkspaceArtifactContractV1(rules=(_RULE,), open_api_hosts=("API.Example.org", "hn.algolia.com"))
    assert contract.open_api_hosts == ("api.example.org", "hn.algolia.com")


@pytest.mark.parametrize(
    "bad",
    [("https://api.example.org",), ("api.example.org/v1",), ("api.example.org", "api.example.org"),
     ("",), ("api example.org",)],
)
def test_contract_rejects_malformed_hosts(bad: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        WorkspaceArtifactContractV1(rules=(_RULE,), open_api_hosts=bad)


def test_every_frozen_contract_still_loads_with_no_hosts() -> None:
    frozen = sorted(Path("contracts").glob("tool-*-v*.yaml"))
    assert frozen, "应有已冻结的工作区合同"
    seen = 0
    for path in frozen:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tool = doc.get("tool") or {}
        raw = tool.get("workspace_contract") or doc.get("workspace_contract")
        if not isinstance(raw, dict):
            continue
        contract = WorkspaceArtifactContractV1.model_validate(raw)
        if str(tool.get("delivery_profile_id") or "") == "open_api_workspace_v1":
            # A frozen open-API task declares the hosts its producer may read.
            assert contract.open_api_hosts, path.name
        else:
            assert contract.open_api_hosts == (), path.name
        seen += 1
    assert seen >= 5
