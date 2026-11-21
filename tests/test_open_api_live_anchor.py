"""开放 API 夹具集必须含一个真实资源场景(live anchor)(incident-live-probe-misreads-fictional-resource-*,两起)。

第一起:虚构仓库的 404 旁边有同型 2xx,探针已学会记 RESOURCE_NOT_LIVE。第二起(同因另一面):
夹具里每个仓库都是虚构的,四条请求全 404、没有任何同型 2xx,探针判 ENDPOINT_GONE 终止旅程——
提案文本自己都说「若夹具里全是虚构标识,端点未必真的没了」。探针在自认分不清的证据上判死,
违反「闸门不杀的不许暗中判死」。真因:探针拿夹具(按设计用虚构标识)去问真实主机,却没有
一条已知真实的资源可问。

不变量:
  I1 蓝图可声明 live_anchor(默认 false);起草规则教:开放 API 草稿恰有一个真实资源场景;
  I2 open_api 草稿的蓝图集没有 live_anchor → 投影错误 OPEN_API_LIVE_ANCHOR_MISSING(可修,不是准入拒);
     离线工作区草稿不受影响;修复指引写明该码怎么修;
  I3 readiness:open_api 草稿的蓝图没有 live_anchor → OPEN_API_LIVE_ANCHOR_MISSING 阻塞冻结;
  I4 探针:非 anchor 夹具的 404/410 一律 RESOURCE_NOT_LIVE(信息),即使没有同型 2xx;
     anchor 夹具的 404/410 仍是 ENDPOINT_GONE 边界;
  I5 没有任何 anchor 的旧任务:404 不判死,报告带 NO_LIVE_ANCHOR_FIXTURE 备注;
  I6 新鲜探针场景不设 live_anchor(提示词写明)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from repoproof.adoption.intake import tool_drafter
from repoproof.adoption.intake.draft_readiness import evaluate_draft_readiness
from repoproof.adoption.intake.workspace_fixtures import FixtureBlueprintV1
from repoproof.execution import open_api_replay
from repoproof.runner import open_api_rehearsal as live

_HOST = "api.anon-feeds.dev"
_TASK = "tool-anon-v1"


# ---------------------------------------------------------------- I1 model + teaching
def test_a_blueprint_may_declare_itself_the_live_anchor() -> None:
    plain = FixtureBlueprintV1(blueprint_id="b1", title="t", scenario="s", input_kind="directory", parameters={})
    assert plain.live_anchor is False
    anchor = FixtureBlueprintV1(
        blueprint_id="b2", title="t", scenario="s", input_kind="directory", parameters={}, live_anchor=True
    )
    assert anchor.live_anchor is True
    assert anchor.model_dump(mode="json")["live_anchor"] is True


def test_the_drafting_rules_teach_the_live_anchor() -> None:
    assert "live_anchor" in tool_drafter._OPEN_API_DRAFT_RULES
    assert "OPEN_API_LIVE_ANCHOR_MISSING" in tool_drafter._PROJECTION_REPAIR_INSTRUCTION
    assert "live_anchor" in tool_drafter._WORKSPACE_INPUTS_SYSTEM
    assert "live_anchor" in tool_drafter._FIXTURE_BLUEPRINT_SCHEMA["items"]["properties"]


# ---------------------------------------------------------------- I2 projection
def _requirements(network: str) -> dict:
    return {
        "inputs": [{"kind": "directory", "location": "local", "representation": "utf8_text",
                    "format_label": "config", "role": "r"}],
        "outputs": [{"kind": "directory", "format_id": "workspace_bundle", "format_label": "ws", "role": "r"}],
        "network": network,
        "credentials": "none",
        "lifecycle": "per_invocation",
        "runtime": "local_cpu",
    }


def _rows(*anchors: bool) -> list[dict]:
    return [
        {"blueprint_id": f"b{i}", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters_json": json.dumps({"k": i}), "live_anchor": flag}
        for i, flag in enumerate(anchors)
    ]


def test_normalization_keeps_the_live_anchor_flag() -> None:
    rows = tool_drafter._normalize_fixture_blueprints({"fixture_blueprints": _rows(False, True, False)},
                                                       input_kind="directory")
    assert [row["live_anchor"] for row in rows] == [False, True, False]


def test_an_open_api_blueprint_set_without_an_anchor_is_a_repairable_projection_error() -> None:
    rows = tool_drafter._normalize_fixture_blueprints({"fixture_blueprints": _rows(False, False, False)},
                                                       input_kind="directory")
    with pytest.raises(tool_drafter.DraftProjectionError) as caught:
        tool_drafter._reject_fixture_set_without_live_anchor(_requirements("open_api"), rows)
    assert "OPEN_API_LIVE_ANCHOR_MISSING" in str(caught.value)
    anchored = tool_drafter._normalize_fixture_blueprints({"fixture_blueprints": _rows(False, True, False)},
                                                          input_kind="directory")
    tool_drafter._reject_fixture_set_without_live_anchor(_requirements("open_api"), anchored)
    tool_drafter._reject_fixture_set_without_live_anchor(_requirements("offline"), rows)


# ---------------------------------------------------------------- I3 readiness
def _draft(tmp_path: Path, *, profile: str, anchor: bool) -> Path:
    draft_dir = tmp_path / "draft"
    (draft_dir / "examples").mkdir(parents=True)
    (draft_dir / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    doc = {
        "task_id": _TASK,
        "tool": {
            "name": "anon", "summary": "anonymous", "schema_version": 4, "delivery_profile_id": profile,
            "interface": {"input": {"kind": "directory", "format": "dir"},
                          "output": {"kind": "directory", "format": "workspace"}},
            "workspace_contract": {
                "schema_version": 1,
                "rules": [{"path_pattern": "README.md", "role": "guide", "media_type": "text/markdown",
                           "validation_profile": "text_utf8_v1"}],
                "require_offline_wheelhouse": False,
                "open_api_hosts": [_HOST],
            },
        },
        "capability": {"statement": "s", "output_schema": "WorkspaceBundleV1"},
        "source_repo": {"url": "https://github.com/anon/anon", "resolved_commit": "a" * 40,
                        "distribution": "anon", "import_module": "anon", "license": "MIT"},
        "_delivery_profile": {"schema_version": 1, "profile_id": profile},
        "_intent_contract": {
            "schema_version": 1, "user_goal": "g",
            "commitments": [{"commitment_id": "c1", "public_text": "t", "rationale": "r",
                             "origin": "MODEL_PROPOSED"}],
            "artifact_protocol": {"schema_version": 1, "protocol_id": "p",
                                  "observations": [{"observation_id": "o", "commitment_ids": ["c1"],
                                                    "locator": "l", "value_encoding": "v"}]},
            "delivery": None, "confirmation": None,
        },
    }
    (draft_dir / "draft.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (draft_dir / "fixture_builder.py").write_text("def build(blueprint, output_path):\n    pass\n", encoding="utf-8")
    blueprints = [
        {"blueprint_id": f"b{i}", "title": "t", "scenario": "s", "input_kind": "directory", "parameters": {"k": i},
         "live_anchor": bool(anchor and i == 0)}
        for i in range(3)
    ]
    (draft_dir / "fixture_blueprints.json").write_text(
        json.dumps({"schema_version": 1, "blueprints": blueprints}), encoding="utf-8"
    )
    (draft_dir / "reference_impl.py").write_text("def build_workspace(input_path, output_dir):\n    pass\n",
                                                 encoding="utf-8")
    (draft_dir / "semantic_verifier.py").write_text("def verify(input_path, artifact_path):\n    return {'ok': True}\n",
                                                    encoding="utf-8")
    (draft_dir / "reference.lock.txt").write_text("anon==1.0\n", encoding="utf-8")
    return draft_dir


def _codes(draft_dir: Path) -> set[str]:
    report = evaluate_draft_readiness(yaml.safe_load((draft_dir / "draft.yaml").read_text()), draft_dir)
    return set(report.reason_codes)


def test_open_api_draft_without_a_live_anchor_cannot_freeze(tmp_path: Path) -> None:
    assert "OPEN_API_LIVE_ANCHOR_MISSING" in _codes(_draft(tmp_path, profile="open_api_workspace_v1", anchor=False))


def test_open_api_draft_with_a_live_anchor_passes_this_check(tmp_path: Path) -> None:
    assert "OPEN_API_LIVE_ANCHOR_MISSING" not in _codes(
        _draft(tmp_path, profile="open_api_workspace_v1", anchor=True)
    )


def test_offline_draft_is_not_asked_for_an_anchor(tmp_path: Path) -> None:
    assert "OPEN_API_LIVE_ANCHOR_MISSING" not in _codes(_draft(tmp_path, profile="workspace_bundle_v1", anchor=False))


# ---------------------------------------------------------------- I4/I5 probe
def _project(tmp_path: Path, fixtures: dict[str, list[tuple[str, str]]], anchors: list[str] | None) -> Path:
    root = tmp_path / "project"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / f"{_TASK}.yaml").write_text(
        yaml.safe_dump({"task_id": _TASK, "tool": {"workspace_contract": {"open_api_hosts": [_HOST]}}}),
        encoding="utf-8",
    )
    for fixture, rows in fixtures.items():
        responses = root / "oracle" / _TASK / "fixtures" / fixture / "input" / open_api_replay.RESPONSES_DIRNAME
        responses.mkdir(parents=True)
        manifest = []
        for index, (path, query) in enumerate(rows):
            name = f"r{index}.json"
            (responses / name).write_text(json.dumps({"items": [1]}), encoding="utf-8")
            manifest.append({"method": "GET", "host": _HOST, "path": path, "query": query, "status": 200,
                             "content_type": "application/json", "body": name})
        open_api_replay.write_manifest(responses, manifest)
    if anchors is not None:
        archived = root / "tool_tasks" / "_drafts" / _TASK
        archived.mkdir(parents=True)
        blueprints = [
            {"blueprint_id": fixture, "title": "t", "scenario": "s", "input_kind": "directory",
             "parameters": {}, "live_anchor": fixture in anchors}
            for fixture in fixtures
        ]
        (archived / "fixture_blueprints.json").write_text(
            json.dumps({"schema_version": 1, "blueprints": blueprints}), encoding="utf-8"
        )
    return root


def _fetch_by_url(table: dict[str, int]):
    def fetch(url: str) -> live.LiveFetchResult:
        for needle, status in table.items():
            if needle in url:
                return live.LiveFetchResult(status=status, content_type="application/json", body=b'{"items": [1, 2]}')
        return live.LiveFetchResult(status=200, content_type="application/json", body=b'{"items": [1, 2]}')
    return fetch


def test_a_synthetic_fixture_that_404s_everywhere_is_information_not_a_boundary(tmp_path: Path) -> None:
    # The anchor covers one endpoint shape; the invented scenario also asks another
    # shape the anchor never touched.  No 2xx sibling exists for that shape.
    root = _project(
        tmp_path,
        {"real-world": [("/repos/known/lib/pulls", "state=all")],
         "invented": [("/repos/acme/x/contributors", ""), ("/repos/acme/y/contributors", "")]},
        anchors=["real-world"],
    )
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_by_url({"/contributors": 404}))
    assert report["status"] == "LIVE_OK", report
    assert report["reason_codes"] == []
    codes = {row["path"]: row["code"] for row in report["requests"]}
    assert codes["/repos/acme/x/contributors"] == "RESOURCE_NOT_LIVE"
    assert codes["/repos/known/lib/pulls"] == "OK"
    assert report["live_anchor_fixtures"] == ["real-world"]


def test_the_anchor_fixture_decides_a_gone_endpoint(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        {"real-world": [("/repos/known/lib/pulls", "state=all")],
         "invented": [("/repos/acme/x/pulls", "state=all")]},
        anchors=["real-world"],
    )
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_by_url({"/pulls": 404}))
    assert report["status"] == "LIVE_BOUNDARY"
    assert report["reason_codes"] == ["ENDPOINT_GONE"]
    codes = {row["fixture"]: row["code"] for row in report["requests"]}
    assert codes["real-world"] == "ENDPOINT_GONE"
    assert codes["invented"] == "RESOURCE_NOT_LIVE"


def test_a_task_without_any_anchor_does_not_decide_on_404s(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        {"invented-a": [("/repos/acme/x/pulls", "state=all")], "invented-b": [("/repos/acme/y/pulls", "state=all")]},
        anchors=None,
    )
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_by_url({"/pulls": 404}))
    assert report["status"] == "LIVE_OK", report
    assert report["reason_codes"] == []
    assert "NO_LIVE_ANCHOR_FIXTURE" in report["notes"]
    assert {row["code"] for row in report["requests"]} == {"RESOURCE_NOT_LIVE"}


def test_credentials_and_drift_are_still_boundaries_on_synthetic_fixtures(tmp_path: Path) -> None:
    root = _project(tmp_path, {"invented": [("/search", "q=x")]}, anchors=[])
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_by_url({"/search": 403}))
    assert report["status"] == "LIVE_BOUNDARY"
    assert report["reason_codes"] == ["PLATFORM_REQUIRES_CREDENTIALS"]


# ---- 第三起(plotly):形状漂移与 404 一样,只有真实资源的答复才能说话 ----
# anchor 场景没覆盖两台主机;非 anchor 夹具虚构的 HN item/用户在实况里缺字段、变类型,
# 探针判 RESPONSE_SHAPE_DRIFTED 边界。虚构资源的形状不是端点的形状。


def _fetch_shape(table: dict[str, bytes]):
    def fetch(url: str) -> live.LiveFetchResult:
        for needle, body in table.items():
            if needle in url:
                return live.LiveFetchResult(status=200, content_type="application/json", body=body)
        return live.LiveFetchResult(status=200, content_type="application/json", body=b'{"items": [1, 2]}')
    return fetch


def test_shape_drift_on_a_synthetic_fixture_is_information(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        {"real-world": [("/repos/known/lib/pulls", "state=all")],
         "invented": [("/v0/item/100.json", ""), ("/v0/user/nobody.json", "")]},
        anchors=["real-world"],
    )
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_shape({"/v0/item/100.json": b'{"other": 1}',
                                                 "/v0/user/nobody.json": b"null"}))
    assert report["status"] == "LIVE_OK", report
    assert report["reason_codes"] == []
    codes = {row["path"]: row["code"] for row in report["requests"]}
    assert codes["/v0/item/100.json"] == "RESOURCE_SHAPE_DIFFERS"
    assert codes["/v0/user/nobody.json"] == "RESOURCE_SHAPE_DIFFERS"


def test_shape_drift_on_the_anchor_is_still_a_boundary(tmp_path: Path) -> None:
    root = _project(tmp_path, {"real-world": [("/repos/known/lib/pulls", "state=all")]}, anchors=["real-world"])
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_shape({"/pulls": b'{"other": 1}'}))
    assert report["status"] == "LIVE_BOUNDARY"
    assert report["reason_codes"] == ["RESPONSE_SHAPE_DRIFTED"]


def test_a_declared_host_without_anchor_rows_is_named(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        {"real-world": [("/repos/known/lib/pulls", "state=all")], "invented": [("/v0/item/100.json", "")]},
        anchors=["real-world"],
    )
    # Two declared hosts; the anchor only ever asks the first one.
    (root / "contracts" / f"{_TASK}.yaml").write_text(
        yaml.safe_dump({"task_id": _TASK,
                        "tool": {"workspace_contract": {"open_api_hosts": [_HOST, "other.example.org"]}}}),
        encoding="utf-8",
    )
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live", fetch=_fetch_shape({}))
    assert "HOST_WITHOUT_ANCHOR:other.example.org" in report["notes"]


def test_the_rules_teach_that_the_anchor_covers_every_host() -> None:
    assert "every declared host" in tool_drafter._OPEN_API_DRAFT_RULES


# ---- 第四起(plotly):非 anchor 夹具的 4xx/5xx 也只是信息 ----
# 虚构 handle 的 getAuthorFeed 回 400,被记成 ENDPOINT_ERROR 边界;与 404、形状漂移同理,
# 只有真实资源的答复才能说端点怎么了。


def test_an_error_status_on_a_synthetic_fixture_is_information(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        {"real-world": [("/xrpc/feed", "actor=real.example")], "invented": [("/xrpc/feed", "actor=nobody.example")]},
        anchors=["real-world"],
    )
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_by_url({"nobody.example": 400}))
    assert report["status"] == "LIVE_OK", report
    codes = {row["fixture"]: row["code"] for row in report["requests"]}
    assert codes["invented"] == "RESOURCE_ERROR" and codes["real-world"] == "OK"


def test_an_error_status_on_the_anchor_is_still_a_boundary(tmp_path: Path) -> None:
    root = _project(tmp_path, {"real-world": [("/xrpc/feed", "actor=real.example")]}, anchors=["real-world"])
    report = live.live_probe(project_root=root, task_id=_TASK, out_root=tmp_path / "live",
                             fetch=_fetch_by_url({"real.example": 500}))
    assert report["status"] == "LIVE_BOUNDARY" and report["reason_codes"] == ["ENDPOINT_ERROR"]
