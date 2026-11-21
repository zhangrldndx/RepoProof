"""联网获取的需求不得被静默降成「用户自己去拿快照」(incident-network-intent-silently-downgraded-*)。

两个独立仓库上,用户要的是"每周看一眼几个开源项目的 PR 积压"与"每天看看空气和天气",模型把
delivery_requirements.network 起草成 offline,并发明了一个用户并不拥有的输入(「周快照 JSON」、
「FlatBuffer 响应文件」)。旅程一路绿到彩排——交付的却是另一件产品:用户得自己去联网抓数据。
这是旅程层面的伪成功。

机制:起草前先问模型一个窄问题——这个需求要用到哪些数据、各自在哪(user_local / public_service /
pinned_library),每条附上**请求原文里的证据**;Core 核实证据确是原文子串(模型编不出"用户有快照")。
随后主起草的 network 不得弱于数据来源蕴含的档位:有 public_service 就至少是 open_api。

不变量:
  I1 证据不是请求原文的子串 → DATA_SOURCE_EVIDENCE_NOT_IN_REQUEST;
  I2 有 public_service 来源 → 需要 open_api;全为 user_local/pinned_library → offline 即可;
  I3 network=offline 而存在 public_service 来源 → 投影拒绝 NETWORK_INTENT_DOWNGRADED,签名落在
     delivery_requirements.network,消息点名那条来源;open_api 通过;
  I4 起草提示写明 data_sources 的地位与"不得把公共服务数据变成用户提供的文件"。

同一族的第二种收窄:用户点名要的交付物(电子书、日历文件、可打印 PDF……)被起草成一个 JSON。
窄问题同时读出 deliverables(各附原文证据);合同里每条规则可声明 satisfies;Core 核实每个交付物
至少被一条规则满足,否则投影拒绝 DELIVERABLE_NOT_CONTRACTED。
  I5 交付物证据同样必须是原文子串;每个交付物须被至少一条规则 satisfies;
  I6 未点名交付物的请求不受此约束。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake import tool_drafter

_GOAL = "我关注的几个开源项目，每周看一眼 PR 积压了多少、评审有多慢、谁在干活，要能和前几周比。"


def _sources(origin: str, evidence: str = "每周看一眼 PR 积压了多少") -> dict:
    return {"data_sources": [{"name": "开放 PR 列表", "origin": origin, "evidence": evidence}]}


def test_evidence_must_be_quoted_from_the_request() -> None:
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter.validate_data_sources(
            _sources("public_service", evidence="用户有一份周快照"), capability_goal=_GOAL
        )
    assert "DATA_SOURCE_EVIDENCE_NOT_IN_REQUEST" in str(caught.value)
    admitted = tool_drafter.validate_data_sources(_sources("public_service"), capability_goal=_GOAL)
    assert admitted[0]["origin"] == "public_service"


def test_required_network_follows_the_sources() -> None:
    assert tool_drafter.required_network_for(({"origin": "public_service"},)) == "open_api"
    assert tool_drafter.required_network_for(({"origin": "user_local"}, {"origin": "pinned_library"})) == "offline"
    assert tool_drafter.required_network_for(()) == "offline"


def test_offline_with_a_public_source_is_a_projection_rejection() -> None:
    sources = tool_drafter.validate_data_sources(_sources("public_service"), capability_goal=_GOAL)
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter._reject_network_intent_downgrade({"network": "offline"}, sources)
    assert tool_drafter._projection_rejection_signature(caught.value) == (
        "NETWORK_INTENT_DOWNGRADED",
        "delivery_requirements.network",
    )
    assert "开放 PR 列表" in str(caught.value.__cause__)
    tool_drafter._reject_network_intent_downgrade({"network": "open_api"}, sources)
    tool_drafter._reject_network_intent_downgrade({"network": "offline"}, ({"origin": "user_local", "name": "x"},))


def test_the_prompts_teach_data_sources() -> None:
    assert "data_sources" in tool_drafter._SYSTEM
    assert "public_service" in tool_drafter._INTENT_READING_SYSTEM and "evidence" in tool_drafter._INTENT_READING_SYSTEM
    lowered = tool_drafter._SYSTEM.lower()
    assert "user-supplied file" in lowered or "user-supplied snapshot" in lowered


_EPUB_GOAL = "我订阅的几十个源和 arXiv 上我的方向，每周打包成一本电子书发到 Kindle，已经读过的别再收进来。"


def test_deliverables_need_evidence_and_a_contract_rule() -> None:
    reading = {
        "data_sources": [{"name": "订阅源", "origin": "public_service", "evidence": "我订阅的几十个源"}],
        "deliverables": [{"name": "周电子书", "form": "epub", "evidence": "每周打包成一本电子书"}],
    }
    admitted = tool_drafter.validate_intent_reading(reading, capability_goal=_EPUB_GOAL)
    assert admitted["deliverables"][0]["form"] == "epub"
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter.validate_intent_reading(
            {**reading, "deliverables": [{"name": "周电子书", "form": "epub", "evidence": "一份 JSON 清单"}]},
            capability_goal=_EPUB_GOAL,
        )
    assert "DELIVERABLE_EVIDENCE_NOT_IN_REQUEST" in str(caught.value)
    rules_without = [{"path_pattern": "digest.json", "role": "digest", "satisfies": []}]
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter._reject_uncontracted_deliverables(rules_without, admitted["deliverables"])
    assert tool_drafter._projection_rejection_signature(caught.value) == (
        "DELIVERABLE_NOT_CONTRACTED",
        "workspace_contract.rules",
    )
    assert "周电子书" in str(caught.value.__cause__)
    rules_with = [{"path_pattern": "weekly.epub", "role": "weekly_epub", "satisfies": ["周电子书"]}]
    tool_drafter._reject_uncontracted_deliverables(rules_with, admitted["deliverables"])
    tool_drafter._reject_uncontracted_deliverables(rules_without, ())
