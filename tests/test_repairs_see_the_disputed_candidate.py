"""修复要看的是被争议的那个候选,不是第一个(incident-repairs-blind-to-the-disputed-candidate-*)。

第一起(rich):生产者拒绝的是第三个蓝图(嵌套路径的清单),修复摘录固定物化第一个蓝图——六轮交替看着
一份本来就能读的输入。第二起(ebooklib):争议发生在鲜审场景,判官把导航页当成一章;判官修复的
artifact_observation 读成功后才写的状态文件(失败时为空),输入摘录物化的是冻结蓝图 1。

不变量:
  I1 _fixture_excerpt_for_draft(draft_dir, blueprint_id=…) 物化点名的蓝图,冻结蓝图与鲜审场景两处都查;
  I2 失败时 _record_disputed_candidate 记下蓝图 id、原因码与产出观察;_disputed_candidate 读回;
  I3 判官修复的 artifact_observation 优先用被争议候选的观察;
  I4 zip 容器的观察带文本成员的开头(有界),不只成员名;
  I5 轮次诊断带「DISPUTED_BLUEPRINT: <id>」一行,_disputed_blueprint_id 能读回。
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from repoproof.ui.services import product_jobs

_BUILDER = '''from pathlib import Path


def build(blueprint, output_path):
    params = blueprint["parameters"]
    out = Path(output_path)
    target = out / params["filename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(params["text"])
'''


def _draft(tmp_path: Path) -> Path:
    (tmp_path / "fixture_builder.py").write_text(_BUILDER, encoding="utf-8")
    (tmp_path / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": "one", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {"filename": "pins.txt", "text": "a==1\n"}},
        {"blueprint_id": "three", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {"filename": "nested/pins.txt", "text": "b==2\n"}}]}), encoding="utf-8")
    (tmp_path / "fresh_probe_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": [
        {"blueprint_id": "fresh-x", "title": "t", "scenario": "s", "input_kind": "directory",
         "parameters": {"filename": "fresh.txt", "text": "c==3\n"}}]}), encoding="utf-8")
    return tmp_path


def test_the_excerpt_materialises_the_named_blueprint(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    assert product_jobs._fixture_excerpt_for_draft(draft)["blueprint_id"] == "one"
    named = product_jobs._fixture_excerpt_for_draft(draft, blueprint_id="three")
    assert named["blueprint_id"] == "three" and named["files"] == ["nested/pins.txt"]
    fresh = product_jobs._fixture_excerpt_for_draft(draft, blueprint_id="fresh-x")
    assert fresh["blueprint_id"] == "fresh-x" and fresh["text_heads"]["fresh.txt"].startswith("c==3")
    assert product_jobs._fixture_excerpt_for_draft(draft, blueprint_id="nope")["blueprint_id"] == "one"


def _epub_like(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def test_zip_observation_shows_text_member_heads() -> None:
    payload = _epub_like({"nav.xhtml": "<nav><a>Title A</a><a>Title B</a></nav>", "ch0.xhtml": "<h1>Title A</h1>"})
    row = product_jobs._observe_artifact_payload(payload, budget=4000)
    assert row["zip_members"] == ["nav.xhtml", "ch0.xhtml"]
    assert row["zip_text_heads"]["nav.xhtml"].startswith("<nav><a>Title A</a>")
    assert row["zip_text_heads"]["ch0.xhtml"] == "<h1>Title A</h1>"


def test_the_disputed_candidate_is_recorded_and_preferred(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "digest.epub").write_bytes(_epub_like({"nav.xhtml": "<nav>all titles</nav>"}))
    (expected / "manifest.json").write_text('{"included": []}', encoding="utf-8")
    product_jobs._record_disputed_candidate(
        draft, blueprint_id="fresh-x", reason_code="WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT",
        expected_dir=expected,
    )
    disputed = product_jobs._disputed_candidate(draft)
    assert disputed["blueprint_id"] == "fresh-x"
    paths = [row["path"] for row in disputed["output_observation"]["files"]]
    assert paths == ["digest.epub", "manifest.json"]
    assert disputed["output_observation"]["files"][0]["zip_text_heads"]["nav.xhtml"] == "<nav>all titles</nav>"
    # The judge's repair sees the disputed output even though no state file was ever written.
    observation = product_jobs._self_check_artifact_observation(draft, excluded=())
    assert [row["path"] for row in observation["files"]] == ["digest.epub", "manifest.json"]
    assert observation["blueprint_id"] == "fresh-x"


def test_no_dispute_recorded_yields_nothing(tmp_path: Path) -> None:
    assert product_jobs._disputed_candidate(tmp_path) is None
    (tmp_path / "disputed_candidate.json").write_text("not json", encoding="utf-8")
    assert product_jobs._disputed_candidate(tmp_path) is None


def test_the_round_diagnostics_name_the_disputed_blueprint() -> None:
    rows = ("UserInputError", "UserInputError: nope @ reference_impl.py:9", "DISPUTED_BLUEPRINT: three")
    assert product_jobs._disputed_blueprint_id(rows) == "three"
    assert product_jobs._disputed_blueprint_id(rows[:2]) is None
    assert product_jobs._disputed_blueprint_row("three") == "DISPUTED_BLUEPRINT: three"
