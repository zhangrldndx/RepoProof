"""争议修复要看得见被争议夹具实际录了哪些请求键(incident-repairs-blind-to-the-disputed-candidate-openmeteo-v1)。

第三面:UNRECORDED_REQUEST 在两个主机间乒乓五轮——每轮诊断只有生产者撞到的第一把未录键,而夹具实际录的键
谁都看不到:摘录跳过 __responses__/,recorded_requests 只读蓝图行(构建器代码拼请求时为空)。

不变量:
  I1 _fixture_excerpt_for_draft 的结果带 recorded_requests:物化 manifest 的
     「GET host/path?canonical-query」键(不带响应体);
  I2 _recorded_requests_for_draft 在蓝图行给不出键时回退到物化第一个蓝图的键;蓝图行有键时行为不变;
  I3 没有 __responses__ 的夹具 → recorded_requests 为空列表。
"""

from __future__ import annotations

import json
from pathlib import Path

from repoproof.ui.services import product_jobs

_BUILDER = '''import json
from pathlib import Path


def build(blueprint, output_path):
    params = blueprint["parameters"]
    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps({"city": params["city"]}))
    responses = out / "__responses__"
    responses.mkdir()
    (responses / "b0.json").write_text("{}")
    (responses / "b1.json").write_text("{}")
    rows = [
        {"method": "GET", "host": "api.example.org", "path": "/v1/forecast",
         "query": "longitude=1&latitude=2&hourly=a,b", "status": 200, "content_type": "application/json",
         "body": "b0.json"},
        {"method": "GET", "host": "air.example.org", "path": "/v1/air", "query": "", "status": 200,
         "content_type": "application/json", "body": "b1.json"},
    ]
    (responses / "manifest.json").write_text(json.dumps({"schema_version": 1, "responses": rows}))
'''


def _draft(tmp_path: Path, builder: str = _BUILDER) -> Path:
    (tmp_path / "fixture_builder.py").write_text(builder, encoding="utf-8")
    (tmp_path / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": "one", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {"city": "Anytown"}}]}), encoding="utf-8")
    return tmp_path


def test_the_excerpt_lists_the_recorded_keys(tmp_path: Path) -> None:
    excerpt = product_jobs._fixture_excerpt_for_draft(_draft(tmp_path))
    assert excerpt["files"] == ["config.json"]
    assert excerpt["recorded_requests"] == [
        "GET air.example.org/v1/air",
        "GET api.example.org/v1/forecast?hourly=a%2Cb&latitude=2&longitude=1",
    ]


def test_recorded_requests_fall_back_to_the_materialised_keys(tmp_path: Path) -> None:
    assert product_jobs._recorded_requests_for_draft(_draft(tmp_path)) == [
        "GET air.example.org/v1/air",
        "GET api.example.org/v1/forecast?hourly=a%2Cb&latitude=2&longitude=1",
    ]


def test_blueprint_rows_still_win_when_present(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    (draft / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": "one", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {"city": "Anytown", "recordings": [{"host": "rows.example.org", "path": "/x", "query": {}}]}}]}),
        encoding="utf-8")
    assert product_jobs._recorded_requests_for_draft(draft) == ["GET rows.example.org/x"]


def test_a_fixture_without_recordings_has_no_keys(tmp_path: Path) -> None:
    builder = (
        "from pathlib import Path\n\n\ndef build(blueprint, output_path):\n"
        "    Path(output_path).mkdir(parents=True, exist_ok=True)\n"
        "    (Path(output_path) / 'a.txt').write_text(blueprint['parameters']['city'])\n"
    )
    excerpt = product_jobs._fixture_excerpt_for_draft(_draft(tmp_path, builder))
    assert excerpt["recorded_requests"] == []
    assert product_jobs._recorded_requests_for_draft(tmp_path) == []
