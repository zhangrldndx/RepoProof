"""判别探针不改上游原样交付的文件;文档被 schema 拒时要说是哪条约束
(incident-discrimination-probe-mutates-upstream-copies-*)。

d1(plotly)attempt-13:上游包自带的 3.5 MB plotly.min.js 被逐字节复制交付,判别探针改它的第 1815 行要
判官拒绝;判官修复三次被以 INVALID_MODEL_OUTPUT_INVALID_DOCUMENT 回滚(schema 只说无效);上游自带文件的
真值是「与上游逐字节相同」,Harness 已按哈希把关。

不变量:
  I1 与钉版上游树中某文件逐字节相同的交付文件不进变异探针,记入 provenance_bound;修改过的副本照旧探;
  I2 normalize_verifier_document 的 INVALID_DOCUMENT 带 diagnostics(loc/type/msg,含 maxLength 之类的约束名)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repoproof.adoption.intake import tool_drafter
from repoproof.verification.workspace_semantic import probe_workspace_verifier_discrimination

_VERIFIER = '''from pathlib import Path

import miniworkspace


def verify(input_path: Path, artifact_path: Path) -> dict:
    miniworkspace.render("x")
    readme = (artifact_path / "README.md").read_text(encoding="utf-8")
    ok = readme == "# Experiment\\n"
    return {"ok": ok, "reason_codes": [] if ok else ["README_MISMATCH"], "checked_commitment_ids": ["c1"]}
'''


def _world(tmp_path: Path) -> dict[str, Path]:
    upstream = tmp_path / "upstream"
    (upstream / "static").mkdir(parents=True)
    (upstream / "miniworkspace.py").write_text("def render(text):\n    return '# ' + text + '\\n'\n", encoding="utf-8")
    shipped = "/* shipped */\n" + "x" * 2000
    (upstream / "static" / "lib.min.js").write_text(shipped, encoding="utf-8")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "brief.txt").write_text("Experiment", encoding="utf-8")
    artifact = tmp_path / "artifact"
    (artifact / "assets").mkdir(parents=True)
    (artifact / "README.md").write_text("# Experiment\n", encoding="utf-8")
    (artifact / "assets" / "lib.min.js").write_text(shipped, encoding="utf-8")
    (artifact / "assets" / "patched.js").write_text(shipped + "\n// patched", encoding="utf-8")
    verifier = tmp_path / "semantic_verifier.py"
    verifier.write_text(_VERIFIER, encoding="utf-8")
    return {"upstream": upstream, "input": input_dir, "artifact": artifact, "verifier": verifier}


def test_upstream_copies_are_provenance_bound_not_probed(tmp_path: Path) -> None:
    world = _world(tmp_path)
    probe = probe_workspace_verifier_discrimination(
        verifier_source=world["verifier"], input_path=world["input"], artifact_dir=world["artifact"],
        python_exe=sys.executable, upstream_dir=world["upstream"], import_module="miniworkspace",
        isolation_required=False,
    )
    probed = {row.path for row in probe.files}
    assert "assets/lib.min.js" not in probed
    assert "assets/patched.js" in probed and "README.md" in probed
    assert probe.provenance_bound == ("assets/lib.min.js",)


def test_an_invalid_verifier_document_names_the_constraint() -> None:
    with pytest.raises(tool_drafter.DraftError) as caught:
        tool_drafter.normalize_verifier_document({"semantic_verifier": "x" * 30001})
    rows = caught.value.diagnostics
    assert rows and rows[0]["loc"] == "semantic_verifier" and rows[0]["type"] == "maxLength"
    assert "30000" in rows[0]["msg"]
