"""判官修复时要知道录制体的形状(incident-verifier-not-told-the-recorded-requests-*,第二面)。

第一起(bokeh):判官按自己想象的端点在录制里找——已把 recorded_requests(GET 键)交给判官。
第二起(rich):判官四轮坚持「没有带 releases 的 /pypi/click/json 录制体」——录制体有 info.version,
生产者由此算出最新版;判官要的是录制里根本没有的字段。请求键不够,还要形状。

不变量:
  I1 _json_shape 给出有界的形状摘要(键、标量类型、数组长度,深度 2);
  I2 _recorded_body_shapes_for_draft 用草稿的 fixture_builder 物化蓝图,按 GET 键给出每个录制体的形状;
  I3 判官规则教 recorded_body_shapes:只从录制里实际存在的字段重算。
"""

from __future__ import annotations

import json
from pathlib import Path

from repoproof.adoption.intake import tool_drafter
from repoproof.ui.services import product_jobs

_BUILDER = '''import json
from pathlib import Path


def build(blueprint, output_path):
    params = blueprint["parameters"]
    out = Path(output_path)
    (out / "config").mkdir(parents=True)
    (out / "config" / "packages.json").write_text(json.dumps({"packages": [params["package"]]}))
    responses = out / "__responses__"
    responses.mkdir()
    body = {"info": {"name": params["package"], "version": params["latest"]}, "urls": [1, 2, 3]}
    (responses / "body_0000.json").write_text(json.dumps(body))
    (responses / "manifest.json").write_text(json.dumps({"schema_version": 1, "responses": [
        {"method": "GET", "host": "pypi.example.org", "path": "/pypi/" + params["package"] + "/json",
         "query": "", "status": 200, "content_type": "application/json", "body": "body_0000.json"}]}))
'''


def test_json_shape_is_bounded_and_names_keys() -> None:
    shape = product_jobs._json_shape({"info": {"name": "x", "version": "1.0", "deep": {"a": {"b": 1}}}, "urls": [1, 2]})
    assert shape == {"info": {"name": "str", "version": "str", "deep": "object"}, "urls": "array[2]"}
    assert product_jobs._json_shape([{"id": 1}, {"id": 2}]) == "array[2] of {id: int}"


def test_the_draft_reports_each_recorded_body_shape(tmp_path: Path) -> None:
    (tmp_path / "fixture_builder.py").write_text(_BUILDER, encoding="utf-8")
    (tmp_path / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": "one", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {"package": "click", "latest": "8.1.7"}}]}), encoding="utf-8")
    shapes = product_jobs._recorded_body_shapes_for_draft(tmp_path)
    assert shapes == {
        "GET pypi.example.org/pypi/click/json": {"info": {"name": "str", "version": "str"}, "urls": "array[3]"}
    }


def test_the_verifier_rules_teach_the_body_shapes() -> None:
    assert "recorded_body_shapes" in tool_drafter._OPEN_API_VERIFIER_RULES
