"""import 模块推不出来要在入口说出来,而且要先多找几处(incident-import-module-not-inferred-lib-layout-*)。

一个仓库把包放在 lib/<pkg>/(既非根目录也非 src/),intake 推不出 import_module,草稿里是空串;
自检跑完整整一轮、花掉一次生产者修复,才在语义筛查上以一段 pydantic 报文炸掉。

不变量:
  I1 <任意一级子目录>/<归一化发行版名>/__init__.py 能被推出;
  I2 pyproject [tool.setuptools.package-dir] 或 packages 声明的位置能被推出;
  I3 工作区草稿 source_repo.import_module 为空 → 就绪度 IMPORT_MODULE_UNKNOWN,零模型、零自检轮;
  I4 根目录 / src/ 布局的旧行为不变。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoproof.adoption.intake.draft_readiness import evaluate_draft_readiness
from repoproof.adoption.intake.tool_intake import extract_import_module


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_a_lib_layout_package_is_inferred(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {"lib/anonlib/__init__.py": "", "lib/anonlib/core.py": "", "pyproject.toml": "[project]\nname='anonlib'\n"},
    )
    module, _evidence = extract_import_module(root, "anonlib")
    assert module == "anonlib"


def test_a_setuptools_package_dir_is_honoured(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "python/anon_sdk/__init__.py": "",
            "pyproject.toml": "[project]\nname='anon-sdk'\n[tool.setuptools.package-dir]\n'' = 'python'\n",
        },
    )
    module, _evidence = extract_import_module(root, "anon-sdk")
    assert module == "anon_sdk"


def test_root_and_src_layouts_are_unchanged(tmp_path: Path) -> None:
    assert extract_import_module(_repo(tmp_path, {"pkg/__init__.py": ""}), "pkg")[0] == "pkg"
    assert extract_import_module(_repo(tmp_path / "b", {"src/pkg/__init__.py": ""}), "pkg")[0] == "pkg"


def _draft(tmp_path: Path, *, import_module: str) -> Path:
    draft_dir = tmp_path / "draft"
    (draft_dir / "examples").mkdir(parents=True)
    (draft_dir / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    doc = {
        "task_id": "tool-anon-v1",
        "tool": {
            "name": "anon",
            "summary": "anonymous",
            "schema_version": 4,
            "delivery_profile_id": "workspace_bundle_v1",
            "interface": {
                "input": {"kind": "directory", "format": "dir"},
                "output": {"kind": "directory", "format": "workspace"},
            },
            "workspace_contract": {
                "schema_version": 1,
                "rules": [
                    {
                        "path_pattern": "README.md",
                        "role": "guide",
                        "media_type": "text/markdown",
                        "validation_profile": "text_utf8_v1",
                    }
                ],
                "require_offline_wheelhouse": False,
            },
        },
        "capability": {"statement": "s", "output_schema": "WorkspaceBundleV1"},
        "source_repo": {
            "url": "https://github.com/anon/anon",
            "resolved_commit": "a" * 40,
            "distribution": "anon",
            "import_module": import_module,
            "license": "MIT",
        },
        "_delivery_profile": {"schema_version": 1, "profile_id": "workspace_bundle_v1"},
        "_intent_contract": {
            "schema_version": 1, "user_goal": "g",
            "commitments": [
                {"commitment_id": "c1", "public_text": "t", "rationale": "r", "origin": "MODEL_PROPOSED"}
            ],
            "artifact_protocol": {
                "schema_version": 1,
                "protocol_id": "p",
                "observations": [
                    {"observation_id": "o", "commitment_ids": ["c1"], "locator": "l", "value_encoding": "v"}
                ],
            },
            "delivery": None, "confirmation": None,
        },
    }
    (draft_dir / "draft.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (draft_dir / "fixture_builder.py").write_text("def build(blueprint, output_path):\n    pass\n", encoding="utf-8")
    blueprints = [
        {"blueprint_id": f"b{i}", "title": "t", "scenario": "s", "input_kind": "directory", "parameters": {"k": i}}
        for i in range(3)
    ]
    (draft_dir / "fixture_blueprints.json").write_text(
        json.dumps({"schema_version": 1, "blueprints": blueprints}), encoding="utf-8"
    )
    (draft_dir / "reference_impl.py").write_text(
        "def build_workspace(input_path, output_dir):\n    pass\n", encoding="utf-8"
    )
    (draft_dir / "semantic_verifier.py").write_text(
        "def verify(input_path, artifact_path):\n    return {'ok': True}\n", encoding="utf-8"
    )
    (draft_dir / "reference.lock.txt").write_text("anon==1.0\n", encoding="utf-8")
    return draft_dir


def _codes(draft_dir: Path) -> set[str]:
    report = evaluate_draft_readiness(yaml.safe_load((draft_dir / "draft.yaml").read_text()), draft_dir)
    return set(report.reason_codes)


def test_an_empty_import_module_blocks_before_any_self_check(tmp_path: Path) -> None:
    assert "IMPORT_MODULE_UNKNOWN" in _codes(_draft(tmp_path, import_module=""))
    assert "IMPORT_MODULE_UNKNOWN" not in _codes(_draft(tmp_path / "ok", import_module="anon"))
