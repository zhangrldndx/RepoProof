"""彩排时对真实主机问一次边界;审核时把录制换成今天的真实响应(m6.4 prework 8)。

冻结前后的每一次验证都对着录制跑——密封的代价是它证明不了"这个主机今天还这样回答"。
彩排是唯一该问实况的时刻,而且要在烧真模型预算之前:主机要凭证/付费了、限流了、端点
没了、响应形状变了,都要说出来,并给用户一份降级提案让其自行抉择。

抓取函数可注入;默认实现只做 GET、不带任何凭证、限时限量。这里永远不把实况响应当真值:
它只用来判断边界与形状,以及作为**审核**输入的录制(制品仍由冻结的生产者与判官裁决)。
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from repoproof.execution.open_api_replay import (
    MANIFEST_FILENAME,
    RESPONSES_DIRNAME,
    canonical_query,
    json_shape,
    write_manifest,
)

MAX_LIVE_REQUESTS = 12
MAX_LIVE_BODY_BYTES = 8 * 1024 * 1024
LIVE_TIMEOUT_SECONDS = 15
_USER_AGENT = "RepoProof-rehearsal/1 (read-only live probe)"


@dataclass(frozen=True)
class LiveFetchResult:
    status: int | None
    content_type: str = ""
    body: bytes = b""
    error: str = ""


FetchFn = Callable[[str], LiveFetchResult]


def default_fetch(url: str) -> LiveFetchResult:
    """One credential-free GET with a bounded body; errors become facts, not exceptions."""

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=LIVE_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_LIVE_BODY_BYTES + 1)
            return LiveFetchResult(
                status=int(response.status),
                content_type=str(response.headers.get("Content-Type") or ""),
                body=body[:MAX_LIVE_BODY_BYTES],
            )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(MAX_LIVE_BODY_BYTES)
        except OSError:
            body = b""
        return LiveFetchResult(
            status=int(exc.code), content_type=str(exc.headers.get("Content-Type") or ""), body=body
        )
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return LiveFetchResult(status=None, error=f"{type(exc).__name__}: {exc}"[:200])


# ---------------------------------------------------------------- frozen facts
def contract_open_api_hosts(project_root: Path, task_id: str) -> tuple[str, ...]:
    path = Path(project_root) / "contracts" / f"{task_id}.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    contract = ((document.get("tool") or {}).get("workspace_contract") or {}) if isinstance(document, dict) else {}
    hosts = contract.get("open_api_hosts") if isinstance(contract, dict) else None
    return tuple(str(item).strip().lower() for item in (hosts or ()) if str(item).strip())


def manifest_rows(responses_dir: Path) -> list[dict]:
    """The raw recorded rows (method, host, path, query, status, content_type, body)."""

    document = json.loads((Path(responses_dir) / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    rows = document.get("responses") if isinstance(document, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def _recorded_requests(project_root: Path, task_id: str) -> list[dict]:
    fixtures = Path(project_root) / "oracle" / task_id / "fixtures"
    seen: dict[tuple[str, str, str], dict] = {}
    for responses in sorted(fixtures.glob(f"*/input/{RESPONSES_DIRNAME}")):
        if responses.is_symlink() or not responses.is_dir():
            continue
        for row in manifest_rows(responses):
            host = str(row.get("host") or "").strip().lower()
            path = "/" + str(row.get("path") or "").strip().lstrip("/")
            query = canonical_query(str(row.get("query") or ""))
            key = (host, path, query)
            if key in seen or str(row.get("method") or "GET").upper() != "GET":
                continue
            body_path = responses / str(row.get("body") or "")
            seen[key] = {
                "host": host,
                "path": path,
                "query": query,
                "status": int(row.get("status") or 200),
                "content_type": str(row.get("content_type") or ""),
                "body": body_path.read_bytes() if body_path.is_file() else b"",
                "fixture": responses.parent.parent.name,
            }
    return list(seen.values())


def live_anchor_fixtures(project_root: Path, task_id: str) -> frozenset[str] | None:
    """Fixture ids whose identifiers are real (``live_anchor``), or None for a task drafted before the flag."""

    path = Path(project_root) / "tool_tasks" / "_drafts" / task_id / "fixture_blueprints.json"
    if path.is_symlink() or not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = document.get("blueprints") if isinstance(document, dict) else None
    return frozenset(
        str(row.get("blueprint_id") or "")
        for row in rows or ()
        if isinstance(row, dict) and bool(row.get("live_anchor"))
    )


# ---------------------------------------------------------------- judgement
def _is_json(content_type: str, body: bytes) -> bool:
    if "json" in content_type.lower():
        return True
    head = body.lstrip()[:1]
    return head in (b"{", b"[")


def shape_drift(seed: dict, live: LiveFetchResult) -> str | None:
    """What the seed recording relied on that the live response no longer offers."""

    if not _is_json(seed["content_type"], seed["body"]):
        return None if live.body else "实况响应为空"
    try:
        seed_doc = json.loads(seed["body"].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    try:
        live_doc = json.loads(live.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "实况响应不是 JSON"
    if isinstance(seed_doc, dict) != isinstance(live_doc, dict):
        return "实况响应的顶层类型变了(对象/数组)"
    if isinstance(seed_doc, dict):
        missing = sorted(set(seed_doc) - set(live_doc))
        return f"实况响应缺少录制依赖的字段:{', '.join(missing)}" if missing else None
    if isinstance(seed_doc, list) and seed_doc and live_doc and isinstance(seed_doc[0], dict):
        first = live_doc[0]
        if not isinstance(first, dict):
            return "实况数组的元素不再是对象"
        missing = sorted(set(seed_doc[0]) - set(first))
        return f"实况元素缺少录制依赖的字段:{', '.join(missing)}" if missing else None
    return None


def classify(seed: dict, live: LiveFetchResult) -> tuple[str, str]:
    """(code, detail) for one live answer; code ``OK`` means usable today."""

    status = live.status
    if status is None:
        return "HOST_UNREACHABLE", live.error or "连接失败"
    if status in (401, 402, 403):
        return "PLATFORM_REQUIRES_CREDENTIALS", f"HTTP {status}"
    if status == 429:
        return "RATE_LIMITED", "HTTP 429"
    if status in (404, 410):
        return "ENDPOINT_GONE", f"HTTP {status}"
    if status == 405:
        return "METHOD_NOT_ALLOWED", "HTTP 405"
    if not 200 <= status < 300:
        return "ENDPOINT_ERROR", f"HTTP {status}"
    drift = shape_drift(seed, live)
    if drift:
        return "RESPONSE_SHAPE_DRIFTED", drift
    return "OK", f"HTTP {status}"


_PROPOSALS: dict[str, tuple[str, str]] = {
    "PLATFORM_REQUIRES_CREDENTIALS": (
        "PLATFORM_ACCESS",
        "主机 {hosts} 现在要求凭证或付费({details})。密封交付不携带凭证,当前 profile 不支持。"
        "可选,请你抉择:① 由你自行决定是否为该平台付费/提供凭证(需另立支持凭证的 profile);"
        "② 改用免凭证、只读的公共 API 主机重新起草(新任务版本);③ 改题。",
    ),
    "RATE_LIMITED": (
        "AVAILABILITY",
        "主机 {hosts} 对无凭证请求限流({details})。可选:① 减少每次调用的请求数或改用批量端点(新任务版本);"
        "② 稍后重跑彩排;③ 改用限额更宽的公共 API 主机。",
    ),
    "ENDPOINT_GONE": (
        "RECORDING",
        "录制里的端点在 {hosts} 上连真实资源场景(live_anchor)也回 404/410({details})——这不是虚构标识的缘故,"
        "端点本身不在了。可选:① 改用该平台当前的端点并按实况重新录制夹具(新任务版本);② 换主机;③ 改题。",
    ),
    "METHOD_NOT_ALLOWED": (
        "RECORDING",
        "主机 {hosts} 的端点不接受 GET({details})。当前 profile 只发 GET,密封回放也只录 GET;这不会「稍后」好。"
        "可选:① 改用该主机的 GET 端点或另一台声明主机(新任务版本);② 改题。",
    ),
    "ENDPOINT_ERROR": (
        "AVAILABILITY",
        "主机 {hosts} 返回错误({details})。可选:① 稍后重跑彩排;② 换端点或主机(新任务版本)。",
    ),
    "HOST_UNREACHABLE": (
        "AVAILABILITY",
        "主机 {hosts} 不可达({details})。请确认本机网络;可选:① 稍后重跑彩排;② 换主机(新任务版本)。",
    ),
    "RESPONSE_SHAPE_DRIFTED": (
        "RECORDING",
        "主机 {hosts} 今天的响应与录制的形状不同:{details}。可选:① 按实况重新录制夹具并调整生产者/判官(新任务版本);"
        "② 换端点或主机;③ 改题。",
    ),
    "UNDECLARED_HOST_IN_RECORDING": (
        "RECORDING",
        "录制里出现了合同未声明的主机 {hosts}。密封运行只把声明的主机映射到桩,这些请求必然失败。"
        "可选:① 在合同 open_api_hosts 里补声明(新任务版本);② 去掉这些请求。",
    ),
}
_SEVERITY = (
    "PLATFORM_REQUIRES_CREDENTIALS",
    "UNDECLARED_HOST_IN_RECORDING",
    "ENDPOINT_GONE",
    "METHOD_NOT_ALLOWED",
    "RESPONSE_SHAPE_DRIFTED",
    "RATE_LIMITED",
    "ENDPOINT_ERROR",
    "HOST_UNREACHABLE",
)


def _endpoint_shape(row: dict) -> tuple[str, int, str, str]:
    """Same host, same segment count, same first and last segment: one endpoint, many resources."""

    segments = [part for part in str(row.get("path") or "").split("/") if part]
    first, last = (segments[0], segments[-1]) if segments else ("", "")
    return (str(row.get("host") or ""), len(segments), first, last)


def _soften_resource_misses(findings: list[dict]) -> None:
    """A 404 beside live siblings of the same endpoint is a missing resource, not a gone endpoint.

    Fixtures name synthetic repositories, handles and ids; the real host
    answers 404 for those while the endpoint itself is alive — the same path
    shape answered 2xx for the real identifiers
    (incident-live-probe-misreads-fictional-resource-*).
    """

    alive: set[tuple[str, int, str, str]] = {
        _endpoint_shape(row) for row in findings if row.get("code") == "OK"
    }
    for row in findings:
        if row.get("code") == "ENDPOINT_GONE" and _endpoint_shape(row) in alive:
            row["code"] = "RESOURCE_NOT_LIVE"
            row["detail"] = (
                f"{row.get('detail') or ''}; the same endpoint answered 2xx for other resources — "
                "this fixture names a resource the host does not have (a synthetic identifier), not a gone endpoint"
            ).strip("; ")


def _soften_synthetic_misses(findings: list[dict], anchors: frozenset[str] | None) -> None:
    """Only a real resource's 404 says the endpoint is gone.

    Every other fixture names invented identifiers by design; its 404 is
    information about the fixture, not about the host — with or without a
    live sibling.  A task drafted before the anchor flag has no anchor to ask
    and therefore does not decide (second incident of
    incident-live-probe-misreads-fictional-resource-*).
    """

    softened = {
        "ENDPOINT_GONE": ("RESOURCE_NOT_LIVE", "its 404"),
        "RESPONSE_SHAPE_DRIFTED": ("RESOURCE_SHAPE_DIFFERS", "the shape of its answer"),
        # An invented handle answers 400/422 as readily as 404 (fourth incident).
        "ENDPOINT_ERROR": ("RESOURCE_ERROR", "its error status"),
    }
    for row in findings:
        code = row.get("code")
        if code not in softened:
            continue
        if anchors and str(row.get("fixture") or "") in anchors:
            continue
        # A missing field, a null body or an error status for an invented
        # item/user describes a resource that never existed, not the endpoint.
        row["code"], what = softened[code]
        row["detail"] = (
            f"{row.get('detail') or ''}; this fixture names invented identifiers — {what} says nothing "
            "about the endpoint" + ("" if anchors else "; the task has no live_anchor fixture to ask")
        ).strip("; ")


def _hosts_without_anchor(hosts, findings: list[dict], anchors: frozenset[str] | None) -> list[str]:
    """Declared hosts the anchor scenario never asked: nothing about them was decided."""

    if not anchors:
        return []
    asked = {str(row.get("host") or "") for row in findings if str(row.get("fixture") or "") in anchors}
    return [f"HOST_WITHOUT_ANCHOR:{host}" for host in hosts if host not in asked]


def downgrade_proposal(findings: list[dict]) -> dict | None:
    """One proposal per boundary class, the most decisive class first."""

    grouped: dict[str, list[dict]] = {}
    for row in findings:
        # Informational codes (a synthetic resource the host lacks) are not boundaries.
        if row.get("code") in _SEVERITY:
            grouped.setdefault(str(row["code"]), []).append(row)
    if not grouped:
        return None
    ordered = [code for code in _SEVERITY if code in grouped]
    parts: list[str] = []
    for code in ordered:
        rows = grouped[code]
        hosts = ", ".join(sorted({str(r.get("host") or "") for r in rows}))
        details = "; ".join(
            f"{r.get('path')}{'?' + r['query'] if r.get('query') else ''}: {r.get('detail')}" for r in rows[:4]
        )
        parts.append(_PROPOSALS[code][1].format(hosts=hosts, details=details))
    return {"kind": _PROPOSALS[ordered[0]][0], "codes": ordered, "text": " ".join(parts)}


# ---------------------------------------------------------------- the probe
def _utc_stamp() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def live_probe(
    *,
    project_root: Path,
    task_id: str,
    out_root: Path,
    fetch: FetchFn = default_fetch,
    max_requests: int = MAX_LIVE_REQUESTS,
) -> dict:
    """Ask every recorded request of a frozen open-API task against today's real host.

    Returns ``NOT_APPLICABLE`` for offline tasks, ``LIVE_OK`` with a live
    recording on disk when every answer is usable, and ``LIVE_BOUNDARY`` with
    reason codes plus a downgrade proposal otherwise.  Never raises for a
    network condition: those are the facts this probe exists to report.
    """

    hosts = contract_open_api_hosts(Path(project_root), task_id)
    if not hosts:
        return {"status": "NOT_APPLICABLE", "reason_codes": [], "requests": [], "live_recording": None}
    requests = _recorded_requests(Path(project_root), task_id)[: max(1, int(max_requests))]
    findings: list[dict] = []
    live_rows: list[tuple[dict, LiveFetchResult]] = []
    for seed in requests:
        row = {"host": seed["host"], "path": seed["path"], "query": seed["query"], "fixture": seed["fixture"]}
        if seed["host"] not in hosts:
            findings.append({**row, "status": None, "code": "UNDECLARED_HOST_IN_RECORDING", "detail": "未声明"})
            continue
        url = f"https://{seed['host']}{seed['path']}" + (f"?{seed['query']}" if seed["query"] else "")
        live = fetch(url)
        code, detail = classify(seed, live)
        finding = {**row, "status": live.status, "code": code, "detail": detail}
        if code == "RESPONSE_SHAPE_DRIFTED":
            # What the world answered with, so a redraft records that shape
            # instead of imagining one again (incident-drift-redraft-without-live-shape-*).
            try:
                finding["live_shape"] = json_shape(json.loads(live.body.decode("utf-8", errors="replace")))
            except (ValueError, AttributeError):
                finding["live_shape"] = "non-json body"
        findings.append(finding)
        if code == "OK":
            live_rows.append((seed, live))
    _soften_resource_misses(findings)
    anchors = live_anchor_fixtures(Path(project_root), task_id)
    _soften_synthetic_misses(findings, anchors)
    codes = [code for code in _SEVERITY if any(f["code"] == code for f in findings)]
    recording: Path | None = None
    if live_rows:
        recording = Path(out_root) / task_id / _utc_stamp() / RESPONSES_DIRNAME
        recording.mkdir(parents=True, exist_ok=True)
        rows = []
        for index, (seed, live) in enumerate(live_rows, start=1):
            name = f"{index:03d}.body"
            (recording / name).write_bytes(live.body)
            rows.append(
                {
                    "method": "GET",
                    "host": seed["host"],
                    "path": seed["path"],
                    "query": seed["query"],
                    "status": int(live.status or 200),
                    "content_type": live.content_type or seed["content_type"],
                    "body": name,
                }
            )
        write_manifest(recording, rows)
    proposal = downgrade_proposal(findings)
    return {
        "status": "LIVE_BOUNDARY" if codes else "LIVE_OK",
        "reason_codes": codes,
        "requests": findings,
        "hosts": list(hosts),
        "live_recording": str(recording) if recording is not None else None,
        "downgrade_proposal": proposal,
        "live_anchor_fixtures": sorted(anchors) if anchors is not None else None,
        "notes": (
            ["NO_LIVE_ANCHOR_FIXTURE"] if not anchors else _hosts_without_anchor(hosts, findings, anchors)
        ),
        "probed_at": _utc_stamp(),
    }


def refresh_recording_live(
    responses_dir: Path,
    *,
    hosts: tuple[str, ...] | list[str],
    fetch: FetchFn = default_fetch,
    max_requests: int = MAX_LIVE_REQUESTS,
) -> dict:
    """Replace a builder's synthetic bodies with today's real answers, row by row.

    Used for the post-freeze fresh audit: the frozen producer and judge then run
    on data the world actually served.  A row whose live answer is unusable
    keeps its synthetic body and is reported; nothing is silently swapped.
    """

    responses_dir = Path(responses_dir)
    allowed = {str(item).strip().lower() for item in hosts}
    rows = manifest_rows(responses_dir)
    refreshed = 0
    failed: list[dict] = []
    for row in rows[: max(1, int(max_requests))]:
        host = str(row.get("host") or "").strip().lower()
        path = "/" + str(row.get("path") or "").strip().lstrip("/")
        query = canonical_query(str(row.get("query") or ""))
        body_path = responses_dir / str(row.get("body") or "")
        if host not in allowed or not body_path.is_file():
            failed.append({"host": host, "path": path, "code": "UNDECLARED_HOST_IN_RECORDING"})
            continue
        seed = {"content_type": str(row.get("content_type") or ""), "body": body_path.read_bytes()}
        live = fetch(f"https://{host}{path}" + (f"?{query}" if query else ""))
        code, detail = classify(seed, live)
        if code != "OK":
            failed.append({"host": host, "path": path, "code": code, "detail": detail})
            continue
        body_path.write_bytes(live.body)
        row["status"] = int(live.status or 200)
        if live.content_type:
            row["content_type"] = live.content_type
        refreshed += 1
    if refreshed:
        write_manifest(responses_dir, rows)
    return {"refreshed": refreshed, "total": len(rows), "failed": failed, "fetched_at": _utc_stamp()}


def copy_recording(source: Path, destination: Path) -> None:
    """Place a live recording where a fixture expects its ``__responses__``."""

    shutil.copytree(Path(source), Path(destination), dirs_exist_ok=True)
