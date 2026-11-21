"""录制行里的 path 是请求路径,不是夹具文件路径(incident-blueprint-sanitiser-mangles-request-path-*)。

蓝图路径值净化器把所有名为 path 的参数当成夹具文件的相对路径:URL 路径 /xrpc/… 不是合法相对路径,
于是被改写成 fixture-<hash>.searchposts。构建器录下一个不存在的路径,生产者请求真正的 URL,桩回
404;六轮 UNRECORDED_REQUEST,两次构建器修复被验证器拒绝回滚且没说原因。

不变量:
  I1 带 host 兄弟键的对象(一条请求录制)里的 path/query 不被投影改写;
  I2 同样的对象通过可移植路径校验;
  I3 没有 host 兄弟键的 path 参数照旧投影/校验(夹具文件名仍须可移植);
  I4 修复回滚时 repair.diagnostics 说出原因。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake.workspace_fixtures import (
    FixtureBlueprintV1,
    FixtureBuilderError,
    project_fixture_blueprint_portable_paths,
    validate_fixture_blueprint_portable_paths,
)

_URL_PATH = "/xrpc/app.bsky.feed.searchPosts"


def _blueprint(parameters: dict, blueprint_id: str = "b1") -> FixtureBlueprintV1:
    return FixtureBlueprintV1(
        blueprint_id=blueprint_id, title="t", scenario="s", input_kind="directory", parameters=parameters
    )


def test_request_rows_keep_their_url_path() -> None:
    row = {"host": "api.example.org", "path": _URL_PATH, "query": {"q": "x"}, "body": {}}
    seed = _blueprint({"recordings": [row]})
    other = {"host": "api.example.org", "path": _URL_PATH, "query": {"q": "y"}, "body": {}}
    candidate = _blueprint({"recordings": [other]}, "b2")
    projected = project_fixture_blueprint_portable_paths(candidate, seeds=(seed,))
    assert projected.parameters["recordings"][0]["path"] == _URL_PATH
    validate_fixture_blueprint_portable_paths(candidate, seeds=(seed,))


def test_plain_path_parameters_are_still_portable() -> None:
    seed = _blueprint({"path": "notes/a.txt"})
    candidate = _blueprint({"path": "/etc/passwd"}, "b2")
    projected = project_fixture_blueprint_portable_paths(candidate, seeds=(seed,))
    assert projected.parameters["path"] != "/etc/passwd"
    assert projected.parameters["path"].startswith("fixture-")
    with pytest.raises(FixtureBuilderError):
        validate_fixture_blueprint_portable_paths(candidate, seeds=(seed,))
