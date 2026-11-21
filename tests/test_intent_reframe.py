"""准入的反提案(m6.4 prework 2)。

此前对"实时监控我的额度"这类需求,准入只会说一句「需求明确要求常驻运行;当前 profile
只支持单次调用」——拒了,没说什么是支持的。操作者的要求:识别到边界时**告知用户、由其
自决、推荐可行的改法**。付费凭证平台(如 X)同理:告知收费,推荐免凭证的公共 API。

不变量:
  I1 常驻/实时 → 可改写为"定期快照 + previous/ 累积",状态 NEED_REFRAME 而非 UNSUPPORTED;
  I2 付费凭证平台 → 告知收费并列出公共 API 替代,状态 NEED_REFRAME;
  I3 改写后的题面必须**自证**可接受:改写文本重新分类须为 supported,否则不提供改写;
  I4 硬边界(凭证、外部写、浏览器、GPU、远程服务)不改写,仍 UNSUPPORTED;
  I5 免凭证的公开 API 抓取本身就是支持的:network=open_api,零原因码;
  I6 否定句照旧:「不要联网」仍是 offline。
"""

from __future__ import annotations

from repoproof.adoption.admission.admission_report import decide_tool_intent
from repoproof.adoption.admission.intent_risk_policy import classify_product_intent_risk

_LIVE_BALANCE = "我想实时监控我的 Codex 和 Claude App 账户余额，随时看到还剩多少额度。"
_TWITTER = "帮我盯着 Tibo 在推特上关于 Codex 的帖子，看发帖时间和内容，推算 Codex 重制的概率。"
_LOGIN_WRITEBACK = "登录我的 GitHub 账户，一直跑着，我关注的仓库有新 issue 就直接在我的线上看板表里加一行。"


def test_live_monitoring_is_reframed_to_snapshots() -> None:
    risk = classify_product_intent_risk(_LIVE_BALANCE)
    assert risk.supported is False
    assert "UNSUPPORTED_LONG_RUNNING_LIFECYCLE" in risk.reason_codes
    assert risk.reframable is True
    assert risk.reframed_capability, "要给出改写后的题面"
    assert any("快照" in row or "非实时" in row for row in risk.reframes)
    again = classify_product_intent_risk(risk.reframed_capability)
    assert again.supported is True, f"改写后的题面必须自证可接受:{risk.reframed_capability!r} → {again.reason_codes}"


def test_paid_platform_is_named_and_public_alternatives_offered() -> None:
    risk = classify_product_intent_risk(_TWITTER)
    assert risk.supported is False and risk.reframable is True
    assert "PLATFORM_ACCESS_PAID_CREDENTIALS" in risk.reason_codes
    text = " ".join(risk.reframes)
    assert ("付费" in text or "收费" in text) and "凭证" in text
    assert "由你" in text or "自行" in text, "要把决定留给用户"
    assert "公共 API" in text or "公开 API" in text
    again = classify_product_intent_risk(risk.reframed_capability)
    assert again.supported is True and again.network == "open_api"
    assert "推特" not in risk.reframed_capability


def test_english_platform_spelling_is_covered() -> None:
    risk = classify_product_intent_risk("Track what Tibo posts on Twitter / X.com about the CLI.")
    assert "PLATFORM_ACCESS_PAID_CREDENTIALS" in risk.reason_codes


def test_public_api_fetch_is_simply_supported() -> None:
    risk = classify_product_intent_risk("从公开的天气 API 获取未来七天预报，生成一个本地看板。")
    assert risk.supported is True
    assert risk.network == "open_api"


def test_negated_network_stays_offline() -> None:
    risk = classify_product_intent_risk("整理本地资料夹，不要联网，也不需要浏览器自动化。")
    assert risk.supported is True and risk.network == "offline"


def test_hard_boundaries_are_not_reframed() -> None:
    risk = classify_product_intent_risk(_LOGIN_WRITEBACK)
    assert risk.supported is False and risk.reframable is False
    assert risk.reframed_capability is None
    report = decide_tool_intent(_LOGIN_WRITEBACK)
    assert report is not None and report.status == "UNSUPPORTED"


def test_a_soft_boundary_next_to_a_hard_one_is_still_hard() -> None:
    risk = classify_product_intent_risk("持续监控实验目录，必须使用显卡加速。")
    assert risk.reframable is False and risk.reframed_capability is None


def test_decide_tool_intent_reports_need_reframe() -> None:
    report = decide_tool_intent(_LIVE_BALANCE)
    assert report is not None
    assert report.status == "NEED_REFRAME"
    assert report.reframed_capability
    assert report.questions, "改写提案要作为待用户确认的问题呈现"
    assert report.executes_third_party_code is False
    assert "UNSUPPORTED_LONG_RUNNING_LIFECYCLE" in report.reason_codes
