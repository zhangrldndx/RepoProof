"""开放 API 工作区的规则要先教后杀(m6.4 prework 5)。

密封运行会以四个公开码判死不守规矩的生产者/构建器(未录制请求、凭证泄露、从未请求桩、
夹具缺录制)。闸门要杀的,提示词必须先教:起草、生产者修复、构建器修复、判官起草/修复、
夹具场景提案六份提示词都要写明开放 API 工作区的约定。

不变量:
  I1 起草提示写明:open_api 选新 profile;合同声明 open_api_hosts;生产者读
     REPOPROOF_OPEN_API_BASE_URLS;构建器为每个主机录 __responses__/manifest.json;不读墙钟;
     smoke_command 不抓取;
  I2 生产者修复提示写明基址覆盖变量与四个公开码的含义;
  I3 构建器修复提示写明 __responses__ 的布局(manifest + 正文文件)与匹配键;
  I4 判官提示写明从 input/__responses__ 独立复算,不联网;
  I5 夹具场景提案提示允许把录制响应的内容作为参数,并说明键与查询串规范化。
"""

from __future__ import annotations

from repoproof.adoption.intake import tool_drafter

_ALL = {
    "draft": tool_drafter._SYSTEM,
    "reference_repair": tool_drafter._WORKSPACE_REFERENCE_REPAIR_SYSTEM,
    "builder_repair": tool_drafter._FIXTURE_BUILDER_REPAIR_SYSTEM,
    "verifier": tool_drafter._VERIFIER_SYSTEM,
    "verifier_repair": tool_drafter._VERIFIER_REPAIR_SYSTEM,
    "fixture_proposals": tool_drafter._WORKSPACE_INPUTS_SYSTEM,
}


def test_drafting_prompt_teaches_the_open_api_contract() -> None:
    text = _ALL["draft"]
    for needle in (
        "open_api_workspace_v1",
        "open_api_hosts",
        "REPOPROOF_OPEN_API_BASE_URLS",
        "__responses__",
        "manifest.json",
    ):
        assert needle in text, needle
    lowered = text.lower()
    assert "wall clock" in lowered or "clock" in lowered
    assert "smoke_command" in text and ("must not fetch" in lowered or "never fetch" in lowered)


def test_reference_repair_prompt_names_the_override_and_the_codes() -> None:
    text = _ALL["reference_repair"]
    assert "REPOPROOF_OPEN_API_BASE_URLS" in text
    for code in (
        "WORKSPACE_REFERENCE_UNRECORDED_REQUEST",
        "WORKSPACE_REFERENCE_CREDENTIAL_LEAK",
        "WORKSPACE_REFERENCE_NO_API_CALLS",
    ):
        assert code in text, code


def test_builder_repair_prompt_describes_the_recording_layout() -> None:
    text = _ALL["builder_repair"]
    assert "__responses__" in text and "manifest.json" in text
    assert "WORKSPACE_REFERENCE_RESPONSES_MISSING" in text
    assert "query" in text.lower()


def test_verifier_prompts_point_at_the_recordings() -> None:
    for key in ("verifier", "verifier_repair"):
        text = _ALL[key]
        assert "__responses__" in text, key
        assert "never" in text.lower() and "network" in text.lower(), key


def test_fixture_proposal_prompt_allows_recorded_content() -> None:
    text = _ALL["fixture_proposals"]
    assert "__responses__" in text or "recorded response" in text.lower()


def test_no_case_identifiers_in_any_prompt() -> None:
    import re

    banned = re.compile(
        r"plotly|bokeh|fpdf|openmeteo|ebooklib|altair|matplotlib|\bgeojson\b|holidays|bluesky|mastodon|algolia",
        re.I,
    )
    for key, text in _ALL.items():
        assert banned.search(text) is None, key
