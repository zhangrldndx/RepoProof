"""Deterministic Product-intent safety classification.

This gate handles only explicit delivery requirements that are outside every
currently supported local, offline, per-invocation Product profile.  It runs
before repository access and before any model call.  The vocabulary describes
generic operating-system and external-system effects; repository names and
task-specific output fields do not belong here.

The classifier intentionally favours precision over recall.  Ambiguous prose
continues to the normal contract-authoring flow, where structured delivery
requirements are checked again.  An explicit high-risk intent, however, must
not consume repository, provider, or Agent work merely to be rejected later.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from repoproof.domain.models import NetworkMode


class IntentDeliveryRiskV1(BaseModel):
    """Public, value-free risk dimensions inferred from explicit user prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    credentials: Literal["none", "required"] = "none"
    # offline: nothing said about the network.  open_api: the prose asks to read
    # public/open interfaces — admitted by open_api_workspace_v1.  required is
    # reserved for model-authored claims that exceed that (never produced here).
    network: NetworkMode = "offline"
    browser: Literal["none", "required"] = "none"
    lifecycle: Literal["per_invocation", "long_running"] = "per_invocation"
    runtime: Literal["local_cpu", "gpu", "remote_service"] = "local_cpu"
    external_side_effects: Literal["none", "reversible", "irreversible"] = "none"
    reason_codes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    # A boundary the user can step around: the proposals (one sentence each)
    # and the rewritten request that provably classifies as supported.  A hard
    # boundary (credentials, external writes, browser, GPU, remote runtime) is
    # never reframed — telling the user "what is supported" must not become
    # "we changed what you asked for".
    reframable: bool = False
    reframes: tuple[str, ...] = ()
    reframed_capability: str | None = None

    @property
    def supported(self) -> bool:
        return not self.reason_codes


_POLARITY_BOUNDARY = re.compile(
    r"[。！？!?；;，,]|\b(?:but|however)\b|(?:但是|但|却)"
)
_ENGLISH_NEGATED_SUFFIX = re.compile(
    r"(?:\bdo not\b|\bdon't\b|\bdoes not\b|\bmust not\b|"
    r"\bshould not\b|\bwithout\b|\bnever\b|\bno(?:\s+need\s+to)?\b)"
    r"(?:[\s\w'/-]{0,64})$"
)
_CHINESE_NEGATED_SUFFIX = re.compile(
    r"(?:无需|无须|不要|不需要|不必|不得|禁止|避免|不)"
    r"(?:再|使用|进行|要求|主动|自动)?[^，。；;,.!?]{0,20}$"
)


def _match_is_explicitly_negated(text: str, start: int) -> bool:
    """Read polarity only inside the clause immediately preceding a match.

    Negation is deliberately lexical and local.  It prevents a statement such
    as ``不要联网`` from becoming an online-runtime requirement, while clause
    and contrast boundaries keep ``不需要浏览器，但是要上传`` classified as an
    external write.  Ambiguous prose continues to contract authoring instead
    of being promoted to a positive unsupported requirement.
    """

    prefix = text[max(0, start - 96):start]
    clause = _POLARITY_BOUNDARY.split(prefix)[-1]
    return bool(
        _ENGLISH_NEGATED_SUFFIX.search(clause)
        or _CHINESE_NEGATED_SUFFIX.search(clause)
    )


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    for pattern in patterns:
        for match in pattern.finditer(text):
            if not _match_is_explicitly_negated(text, match.start()):
                return True
    return False


_CREDENTIAL_PATTERNS = (
    re.compile(r"\b(?:log\s*in|login|sign\s*in|authenticate)\b"),
    re.compile(r"\b(?:use|access)\s+(?:my|a|the)\s+(?:private\s+)?account\b"),
    re.compile(r"(?:登录|登陆|身份认证|访问(?:我的|私人|私有)?(?:账户|账号)|使用(?:我的)?(?:账户|账号))"),
)
_NETWORK_PATTERNS = (
    re.compile(r"\b(?:fetch|download|query)\s+.+\s+from\s+(?:the\s+)?(?:online\s+)?(?:internet|web|api)\b"),
    re.compile(r"\b(?:live|online)\s+(?:website|api|service|data)\b"),
    re.compile(
        r"(?:联网|在线抓取|从(?:在线|远程)?\s*(?:网址|网站|接口|api)"
        r"\s*(?:下载|获取|读取|查询)|调用(?:在线|远程)?\s*api|实时查询(?:网站|接口))"
    ),
)
# Reading an open platform / public API is a supported network mode, not a
# rejection: the prose names an interface meant to be read without an account.
_OPEN_API_PATTERNS = (
    # "公开的天气 API" / "开放平台" / "公共数据接口": a short noun may sit between
    # the qualifier and the interface word.
    re.compile(r"(?:公共|公开|开放)(?:的)?[^，。；;,.!?\s]{0,8}\s*(?:api|接口|平台)"),
    re.compile(r"\b(?:public|open)\s+(?:\w+\s+)?(?:api|apis|platform)\b"),
)
# Known platforms whose *read* access sits outside the credential-free
# support surface.  Platform names are public facts, not case identifiers;
# each entry says what the boundary is and which public routes exist instead.
@dataclass(frozen=True)
class _PlatformBoundary:
    platform: str
    code: str
    detect: tuple[re.Pattern[str], ...]
    note: str
    alternatives: str
    rewrite: tuple[tuple[re.Pattern[str], str], ...]


_PLATFORM_ACCESS_BOUNDARIES: tuple[_PlatformBoundary, ...] = (
    _PlatformBoundary(
        platform="X（Twitter）",
        code="PLATFORM_ACCESS_PAID_CREDENTIALS",
        detect=(
            re.compile(r"推特"),
            re.compile(r"\btwitter\b"),
            re.compile(r"\bx\.com\b"),
            re.compile(r"(?<![a-z0-9])x(?![a-z0-9.])\s*(?:上|平台|的帖子)"),
        ),
        note=(
            "X（Twitter）的读取接口自 2026-02 起没有免费层，需要付费的开发者凭证——"
            "不在支持面内；是否付费由你自行决定。"
        ),
        alternatives=(
            "同一需求可改用免凭证、只读的公共 API：Bluesky 公共 AppView、Mastodon 公开时间线、"
            "GitHub 公开仓库 API、Hacker News Algolia。"
        ),
        rewrite=(
            (re.compile(r"推特"), "公共 API（Bluesky/Mastodon/GitHub/Hacker News）"),
            (
                re.compile(r"\bTwitter\b", re.IGNORECASE),
                "public APIs (Bluesky/Mastodon/GitHub/Hacker News)",
            ),
            (
                re.compile(r"\bX\.com\b", re.IGNORECASE),
                "public APIs (Bluesky/Mastodon/GitHub/Hacker News)",
            ),
            (
                re.compile(r"(?<![A-Za-z0-9])X(?![A-Za-z0-9.])(\s*)(?=上|平台|的帖子)"),
                r"公共 API（Bluesky/Mastodon/GitHub/Hacker News）\1",
            ),
        ),
    ),
)
# "Run forever" becomes "one snapshot per scheduled invocation"; applied to the
# original prose so the rewritten request still reads as the user's own words.
_LIFECYCLE_REWRITES = (
    (re.compile(r"实时监控|持续监控|一直监控|实时监听|后台监听"), "定期快照"),
    (re.compile(r"持续运行|一直运行"), "每次调用运行一次"),
    (re.compile(r"常驻(?:服务|进程)?"), "按定时任务反复调用"),
    (
        re.compile(
            r"\b(?:run continuously|keep running|long[- ]running|as a daemon|daemon)\b",
            re.IGNORECASE,
        ),
        "run once per scheduled invocation",
    ),
    (
        re.compile(r"\b(?:continuously|in real time|forever)\b", re.IGNORECASE),
        "once per scheduled run",
    ),
)
_LIFECYCLE_REFRAME = (
    "常驻/实时监控不在支持面内；可改为非实时：每次调用抓取一次快照写入新的输出目录，"
    "把上一次的输出放进输入目录 previous/ 以累积历史，用系统定时任务反复调用即可得到监控效果。"
    "是否接受这样的改写？"
)

_BROWSER_PATTERNS = (
    re.compile(r"\b(?:browser automation|automate (?:a |the )?browser)\b"),
    re.compile(r"\b(?:open|click|fill|submit)\s+.+\s+(?:on|in)\s+(?:a |the )?(?:website|web page|browser)\b"),
    re.compile(r"(?:浏览器自动化|在(?:网页|网站|浏览器)(?:里|中)?(?:打开|点击|填写|提交))"),
)
_LONG_RUNNING_PATTERNS = (
    re.compile(r"\b(?:daemon|long[- ]running|keep running|run continuously|background listener)\b"),
    re.compile(r"\b(?:watch|monitor)\s+.+\s+(?:continuously|in real time|forever)\b"),
    re.compile(
        r"(?:常驻(?:服务|进程)?|持续运行|一直运行|后台监听|实时监听|"
        r"持续监控|一直监控|实时监控)"
    ),
)
_GPU_PATTERNS = (
    re.compile(r"\b(?:gpu|cuda|rocm)\b"),
    re.compile(r"(?:显卡加速|必须使用显卡|需要\s*gpu)"),
)
_REMOTE_RUNTIME_PATTERNS = (
    re.compile(r"\b(?:deploy|run)\s+.+\s+(?:as|to|on)\s+(?:a )?(?:cloud service|remote server|serverless function)\b"),
    re.compile(r"(?:部署到(?:云端|远程服务器)|作为(?:云服务|在线服务)运行)"),
)
_IRREVERSIBLE_PATTERNS = (
    re.compile(r"\b(?:make|execute|complete|send|submit|place|publish|delete|remove)\b.{0,48}\b(?:payment|transfer|transaction|order|message|post|record|resource|data)\b"),
    re.compile(r"\birreversible\s+(?:external\s+)?(?:action|operation|transaction|change)\b"),
    re.compile(r"(?:处理|执行|发起|完成|进行|提交|发送|发布|删除|购买|下单).{0,16}(?:付款|支付|转账|交易|订单|消息|内容|记录|资源|数据)"),
)
_REVERSIBLE_EXTERNAL_PATTERNS = (
    re.compile(
        r"\b(?:upload|sync|create|update|edit)\b.{0,48}\b(?:cloud\s+drive|"
        r"cloud\s+storage|calendar|ticket|issue|remote\s+service|website|web\s+page)\b"
    ),
    re.compile(
        r"(?:(?:上传|同步).{0,24}(?:云盘|云端|网站|远程服务)|"
        r"在(?:云盘|网站|远程服务|日历|工单系统).{0,24}(?:创建|更新|修改))"
    ),
    # Writing rows into a hosted sheet/board/document is an external write
    # whatever the verb: "在我的线上看板表里加一行".
    re.compile(
        r"(?:在|往|向)(?:我的)?(?:线上|在线|远程|云端)[^，。；;,.!?]{0,16}"
        r"(?:表|看板|文档|日历|工单)[^，。；;,.!?]{0,12}(?:加|写|新增|更新|修改|追加)"
    ),
)


def _platform_boundaries(text: str) -> list[_PlatformBoundary]:
    return [entry for entry in _PLATFORM_ACCESS_BOUNDARIES if _matches(entry.detect, text)]


def _rewrite(original: str, *, long_running: bool, platforms: list[_PlatformBoundary]) -> str:
    text = original
    if long_running:
        for pattern, replacement in _LIFECYCLE_REWRITES:
            text = pattern.sub(replacement, text)
    for entry in platforms:
        for pattern, replacement in entry.rewrite:
            text = pattern.sub(replacement, text)
    return text


def classify_product_intent_risk(
    capability_goal: str, *, _offer_reframe: bool = True
) -> IntentDeliveryRiskV1:
    """Classify only explicit unsupported topology and side-effect intent.

    Two kinds of boundary come out of this.  A *hard* one (credentials, external
    writes, browser, GPU, remote runtime) is reported and stops.  A *soft* one —
    a long-running lifecycle, or a platform whose read access needs paid
    credentials — is reported **together with what is supported**: the rewritten
    request is classified again and only offered when it provably passes.
    """

    text = unicodedata.normalize("NFKC", capability_goal or "").casefold()
    credentials: Literal["none", "required"] = (
        "required" if _matches(_CREDENTIAL_PATTERNS, text) else "none"
    )
    network: NetworkMode = (
        "open_api"
        if _matches(_NETWORK_PATTERNS, text) or _matches(_OPEN_API_PATTERNS, text)
        else "offline"
    )
    browser: Literal["none", "required"] = (
        "required" if _matches(_BROWSER_PATTERNS, text) else "none"
    )
    lifecycle: Literal["per_invocation", "long_running"] = (
        "long_running" if _matches(_LONG_RUNNING_PATTERNS, text) else "per_invocation"
    )
    runtime: Literal["local_cpu", "gpu", "remote_service"] = "local_cpu"
    if _matches(_GPU_PATTERNS, text):
        runtime = "gpu"
    elif _matches(_REMOTE_RUNTIME_PATTERNS, text):
        runtime = "remote_service"
    external_side_effects: Literal["none", "reversible", "irreversible"] = "none"
    if _matches(_IRREVERSIBLE_PATTERNS, text):
        external_side_effects = "irreversible"
    elif _matches(_REVERSIBLE_EXTERNAL_PATTERNS, text):
        external_side_effects = "reversible"
    platforms = _platform_boundaries(text)
    if platforms:
        # Reading a platform is a network need; the boundary is who may read it.
        network = "open_api" if network == "offline" else network

    # The compound class is intentionally dominant: it communicates the real
    # safety boundary instead of presenting two weaker topology mismatches.
    if credentials == "required" and external_side_effects != "none":
        return IntentDeliveryRiskV1(
            credentials=credentials,
            network=network,
            browser=browser,
            lifecycle=lifecycle,
            runtime=runtime,
            external_side_effects=external_side_effects,
            reason_codes=("UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT",),
            blockers=(
                "需求明确要求身份凭证并执行外部写操作；当前 Product profile "
                "只交付无凭证、离线、无外部副作用的本地工具。",
            ),
        )

    reasons: list[str] = []
    blockers: list[str] = []
    hard = False
    if credentials == "required":
        hard = True
        reasons.append("UNSUPPORTED_CREDENTIALS_REQUIRED")
        blockers.append("需求明确要求身份凭证；当前 Product profile 不接收或代管凭证。")
    if external_side_effects == "irreversible":
        hard = True
        reasons.append("UNSUPPORTED_IRREVERSIBLE_EXTERNAL_SIDE_EFFECT")
        blockers.append("需求明确要求不可逆外部操作；当前 Product profile 仅允许无外部副作用的本地运行。")
    elif external_side_effects == "reversible":
        hard = True
        reasons.append("UNSUPPORTED_REVERSIBLE_EXTERNAL_SIDE_EFFECT")
        blockers.append(
            "需求明确要求向外部系统写入；即使可以撤销，当前 Product profile "
            "也只允许在新建的本地产物目录内写入。"
        )
    if browser == "required":
        hard = True
        reasons.append("UNSUPPORTED_BROWSER_REQUIRED")
        blockers.append("需求明确要求浏览器交互；当前 Product profile 不包含浏览器运行时。")
    if runtime == "gpu":
        hard = True
        reasons.append("UNSUPPORTED_GPU_RUNTIME")
        blockers.append("需求明确要求 GPU；当前 Product profile 固定为本地 CPU。")
    elif runtime == "remote_service":
        hard = True
        reasons.append("UNSUPPORTED_REMOTE_SERVICE_RUNTIME")
        blockers.append("需求明确要求远程服务运行；当前 Product profile 只交付本地工具。")

    reframes: list[str] = []
    if lifecycle == "long_running":
        reasons.append("UNSUPPORTED_LONG_RUNNING_LIFECYCLE")
        blockers.append("需求明确要求常驻运行；当前 Product profile 只支持单次调用。")
        reframes.append(_LIFECYCLE_REFRAME)
    for entry in platforms:
        reasons.append(entry.code)
        blockers.append(entry.note)
        reframes.append(f"{entry.note}{entry.alternatives}是否改用公共 API 重新尝试？")

    reframable = bool(reframes) and not hard
    reframed_capability: str | None = None
    if reframable and _offer_reframe:
        candidate = _rewrite(
            capability_goal or "", long_running=lifecycle == "long_running", platforms=platforms
        )
        # The rewrite must prove itself: an offer that still fails admission
        # would send the user around the same loop with different words.
        if candidate != capability_goal and classify_product_intent_risk(
            candidate, _offer_reframe=False
        ).supported:
            reframed_capability = candidate
        else:
            reframable = False

    return IntentDeliveryRiskV1(
        credentials=credentials,
        network=network,
        browser=browser,
        lifecycle=lifecycle,
        runtime=runtime,
        external_side_effects=external_side_effects,
        reason_codes=tuple(sorted(set(reasons))),
        blockers=tuple(blockers),
        reframable=reframable,
        reframes=tuple(reframes) if reframable else (),
        reframed_capability=reframed_capability,
    )
