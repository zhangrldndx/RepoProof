"""生产者拒绝夹具时,双方的修复都要看到那份输入本身(incident-fixture-rejection-repairs-blind-to-the-input-*)。

d9(rich)attempt-4:六轮「依赖清单为空或无有效 name==version 行」,builder/reference 交替五次原话未变——
构建器按自己的理解写清单,生产者按自己的理解解析,谁也没见过对方的产物:修复上下文只有失败原话,
没有夹具文件清单与文本开头;而失败时候选目录已被删除。

不变量:
  I1 _fixture_excerpt_for_draft 用草稿的 fixture_builder 物化第一个蓝图,给出文件清单与文本文件开头(有界);
  I2 FIXTURE_REJECTED / EXECUTION_FAILED / UNRECORDED_REQUEST 的修复上下文带 rejected_input_excerpt。
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
    (out / "config").mkdir(parents=True)
    (out / "config" / "requirements.txt").write_text("\\n".join(params["pins"]) + "\\n")
    (out / "config" / "settings.json").write_text(json.dumps({"priority": params["priority"]}))
    (out / "blob.bin").write_bytes(b"\\x00" * 10)
'''


def test_the_excerpt_lists_files_and_text_heads(tmp_path: Path) -> None:
    (tmp_path / "fixture_builder.py").write_text(_BUILDER, encoding="utf-8")
    (tmp_path / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": "one", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {"pins": ["click>=8", "rich==13.0.0"], "priority": "high"}}]}), encoding="utf-8")
    excerpt = product_jobs._fixture_excerpt_for_draft(tmp_path)
    assert excerpt["blueprint_id"] == "one"
    assert excerpt["files"] == ["blob.bin", "config/requirements.txt", "config/settings.json"]
    assert excerpt["text_heads"]["config/requirements.txt"].startswith("click>=8\nrich==13.0.0")
    assert "blob.bin" not in excerpt["text_heads"]


def test_the_failure_context_carries_the_excerpt_for_input_disputes() -> None:
    assert "WORKSPACE_REFERENCE_FIXTURE_REJECTED" in product_jobs._INPUT_DISPUTE_CODES
    assert "WORKSPACE_REFERENCE_EXECUTION_FAILED" in product_jobs._INPUT_DISPUTE_CODES
    assert "WORKSPACE_REFERENCE_UNRECORDED_REQUEST" in product_jobs._INPUT_DISPUTE_CODES


# ---- 第二面(open-meteo / altair):语义分歧的修复也要看得见输入 ----
# 判官说「07:00 expected False observed True」,生产者说 True——两边按不同的阈值语义读同一份配置,
# 十轮里判官/生产者/合同/构建器都修过,谁也没被给过那份配置里的数值;合同修复「无进展」。
#   I3 WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT 也是输入争议:三方(含 verifier)修复上下文都带摘录。


def test_semantic_disagreement_repairs_also_see_the_input() -> None:
    assert "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT" in product_jobs._INPUT_DISPUTE_CODES
    assert product_jobs._excerpt_targets_for("WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT") == (
        "reference", "builder", "verifier", "contract",
    )
    assert product_jobs._excerpt_targets_for("WORKSPACE_REFERENCE_FIXTURE_REJECTED") == ("reference", "builder")
