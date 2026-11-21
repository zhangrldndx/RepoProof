"""仪表盘的语义在数据层;判别力探针要先改数据层的值(m6.4 prework 10)。

一张机器生成的仪表盘页面,几乎全部字节是图表库样板;数据层是 <script> 里的一段内嵌
JSON(或一个 .json 边车),常常只有一行、极长。逐行取样的探针要么落在样板行,要么在那
一长行的正中间改一个字符——多半改坏 JSON 结构,判官因解析失败而"拒绝",探针把它算作
判别成功,其实判官从未被问到"你有没有重算这些数"。

不变量:
  I1 内嵌 JSON 里至少一个数值被改动,且改动后 JSON 仍可解析、与原值不同(问的是语义,不是语法);
  I2 变异种类以 data-value-<n> 命名,闸门诊断能点名;
  I3 逐行变异与"截断末行"一条不少——只加问题,不减问题;
  I4 没有数据层的文件(纯散文)不出现 data-value 变异,行为与从前一致;
  I5 独立 .json 文件也按数据层处理。
"""

from __future__ import annotations

import json
import re

from repoproof.verification.workspace_semantic import content_mutations

_DASHBOARD = "\n".join(
    [
        '<!doctype html><html lang="en">',
        '<meta charset="utf-8">',
        '<link rel="stylesheet" href="assets/theme.css">',
        "<h1>Signal board</h1>",
        '<div id="chart"></div>',
        '<script type="application/json" id="board-data">'
        + json.dumps({"series": [{"name": "posts", "values": [12.5, 13.0, 14.25, 9]}], "total": 48})
        + "</script>",
        '<script src="assets/vendor.js"></script>',
        "</html>",
    ]
)
_PROSE = "\n".join(["# Notes", "", "The meeting moved to Tuesday.", "Bring the printed agenda.", ""])


def _embedded(text: str) -> dict:
    match = re.search(r'<script type="application/json" id="board-data">(.*?)</script>', text, re.S)
    assert match is not None
    return json.loads(match.group(1))


def test_a_numeric_value_inside_the_embedded_json_is_changed_but_stays_parseable() -> None:
    payload = _DASHBOARD.encode("utf-8")
    mutations = content_mutations(payload, limit=4)
    data_kinds = [kind for kind, _ in mutations if kind.startswith("data-value-")]
    assert data_kinds, [kind for kind, _ in mutations]
    original = _embedded(_DASHBOARD)
    for kind, mutated in mutations:
        if not kind.startswith("data-value-"):
            continue
        changed = _embedded(mutated.decode("utf-8"))  # still parseable
        assert changed != original, kind


def test_line_edits_and_truncation_are_still_asked() -> None:
    payload = _DASHBOARD.encode("utf-8")
    kinds = [kind for kind, _ in content_mutations(payload, limit=4)]
    assert any(kind.startswith("edit-line-") for kind in kinds)
    assert "truncate-last-line" in kinds


def test_prose_without_a_data_layer_is_unchanged() -> None:
    payload = _PROSE.encode("utf-8")
    kinds = [kind for kind, _ in content_mutations(payload, limit=4)]
    assert not any(kind.startswith("data-value-") for kind in kinds)
    assert kinds == [kind for kind, _ in content_mutations(payload, limit=4, input_tokens=())]


def test_a_sidecar_json_file_is_a_data_layer() -> None:
    rows = [{"day": "2026-09-01", "count": 7}, {"day": "2026-09-02", "count": 11}]
    payload = json.dumps({"rows": rows}, indent=2).encode()
    mutations = content_mutations(payload, limit=4)
    data = [(kind, mutated) for kind, mutated in mutations if kind.startswith("data-value-")]
    assert data
    for kind, mutated in data:
        changed = json.loads(mutated.decode("utf-8"))
        assert changed != json.loads(payload.decode("utf-8")), kind
