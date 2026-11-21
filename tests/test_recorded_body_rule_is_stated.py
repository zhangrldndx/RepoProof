"""录制体的规则要在拒绝时说出来(incident-recorded-body-rule-not-stated-*)。

d10(holidays):构建器把响应体放进 __responses__/bodies/ 子目录,四轮原话「recorded body must be a file inside
__responses__: 'bodies/x.json'」——它确实在里面;规则真正要求的是裸文件名(不含目录分隔符),报错没说。

不变量:
  I1 子目录/上跳/缺失的 body 被拒时,消息说出约束(裸文件名、直接位于 __responses__ 下、不含 / 或 ..)并回显原名;
  I2 合规的裸文件名照常加载;
  I3 构建器教学写明同一条规则。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.adoption.intake import tool_drafter
from repoproof.execution.open_api_replay import RESPONSES_DIRNAME, load_manifest


def _responses(tmp_path: Path, body: str) -> Path:
    root = tmp_path / RESPONSES_DIRNAME
    (root / "bodies").mkdir(parents=True)
    (root / "bodies" / "x.json").write_text("{}", encoding="utf-8")
    (root / "x.json").write_text("{}", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({"schema_version": 1, "responses": [
        {"method": "GET", "host": "api.example.org", "path": "/v1/x", "query": "", "status": 200,
         "content_type": "application/json", "body": body}]}), encoding="utf-8")
    return root


def test_a_subdirectory_body_is_refused_with_the_rule(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as caught:
        load_manifest(_responses(tmp_path, "bodies/x.json"))
    message = str(caught.value)
    assert "'bodies/x.json'" in message
    assert "bare file name" in message and "no subdirectory" in message
    assert "'x.json'" in message  # what it should have been


def test_a_bare_body_name_loads(tmp_path: Path) -> None:
    index = load_manifest(_responses(tmp_path, "x.json"))
    assert len(index) == 1


def test_the_builder_teaching_states_the_rule() -> None:
    rules = tool_drafter._OPEN_API_DRAFT_RULES
    text = " ".join(rules) if isinstance(rules, (list, tuple)) else str(rules)
    assert "bare file name" in text and "no subdirector" in text
