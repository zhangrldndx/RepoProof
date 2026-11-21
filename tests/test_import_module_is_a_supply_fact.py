"""导入包名是供给事实:推导要避开非运行时目录,推不出要在自检前定位(incident-import-module-unresolved-reaches-evidence-validator-*)。

d3(fpdf2):仓库顶层有 fpdf/、scripts/、test/ 三个带 __init__.py 的目录,「唯一顶层包」判不出
(只排除了 tests),import_module='';草稿带着空导入包一路跑到判官证据记录,才在
SemanticVerifierEvidenceV2.import_module 的校验上死掉(H28 后终于说出了字段)。

不变量:
  I1 唯一顶层包判定排除非运行时区(test/tests/docs/examples/scripts/tools/benchmarks/ci);
  I2 仍不唯一 → 推不出,原因列出候选;
  I3 自检首轮:source_repo.import_module 为空 → 不跑任何生产者/模型,以 IMPORT_MODULE_UNRESOLVED 定位,
     诊断带 intake 记下的原因(_draft.provenance.import_module);
  I4 import_module 非空 → 自检入口不受影响。
"""

from __future__ import annotations

import json
from pathlib import Path

from repoproof.adoption.intake.tool_intake import extract_import_module
from repoproof.ui.services import product_jobs


def _checkout(tmp_path: Path, dirs: list[str]) -> Path:
    root = tmp_path / "upstream"
    for name in dirs:
        (root / name).mkdir(parents=True)
        (root / name / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "anon2"\n', encoding="utf-8")
    return root


def test_non_runtime_zones_do_not_make_the_package_ambiguous(tmp_path: Path) -> None:
    root = _checkout(tmp_path, ["anon", "scripts", "test", "docs", "benchmarks"])
    module, why = extract_import_module(root, "anon2")
    assert module == "anon", why


def test_two_runtime_packages_stay_ambiguous_and_are_named(tmp_path: Path) -> None:
    root = _checkout(tmp_path, ["anon", "other", "test"])
    module, why = extract_import_module(root, "anon2")
    assert module == ""
    assert "anon" in why and "other" in why


def _draft(*, import_module: str) -> dict:
    return {
        "_draft": {"provenance": {"import_module": "无法定位唯一可导入包:anon/, other/"}},
        "source_repo": {"distribution": "anon2", "import_module": import_module},
        "tool": {
            "delivery_profile_id": "workspace_bundle_v1",
            "delivery_requirements": {"network": "offline"},
            "workspace_contract": {"open_api_hosts": []},
        },
    }


def test_the_self_check_locates_an_unresolved_import_module_first(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "fixture_blueprints.json").write_text(json.dumps({"schema_version": 1, "blueprints": []}))

    def never(*_a, **_k):
        raise AssertionError("no producer, judge or model call may run before the supply fact is checked")

    monkeypatch.setattr(product_jobs, "propose_workspace_fixture_candidates", never)
    round_ = product_jobs._self_check_round(tmp_path, _draft(import_module=""), round_index=1)
    assert round_.check_ok is False
    assert round_.reason_codes == ("IMPORT_MODULE_UNRESOLVED",)
    assert any("anon/, other/" in item for item in round_.diagnostics)
    assert product_jobs._import_module_gap(_draft(import_module="anon")) is None
