"""开放 API 草稿冻结前必须声明主机(m6.4 prework 5)。

不变量:
  I1 open_api_workspace_v1 草稿的合同 open_api_hosts 为空 → readiness 阻塞冻结,码 OPEN_API_HOSTS_MISSING;
  I2 声明了主机 → 该问题不出现;
  I3 workspace_bundle_v1 草稿即使合同带了主机也不受此项影响(离线 profile 不读主机)。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoproof.adoption.intake.draft_readiness import evaluate_draft_readiness


def _draft(tmp_path: Path, *, profile: str, hosts: list[str]) -> Path:
    draft_dir = tmp_path / "draft"
    (draft_dir / "examples").mkdir(parents=True)
    (draft_dir / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    doc = {
        "task_id": "tool-anon-v1",
        "tool": {
            "name": "anon",
            "summary": "anonymous",
            "schema_version": 4,
            "delivery_profile_id": profile,
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
                "open_api_hosts": hosts,
            },
        },
        "capability": {"statement": "s", "output_schema": "WorkspaceBundleV1"},
        "source_repo": {
            "url": "https://github.com/anon/anon", "resolved_commit": "a" * 40,
            "distribution": "anon", "import_module": "anon", "license": "MIT",
        },
        "_delivery_profile": {"schema_version": 1, "profile_id": profile},
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


def test_open_api_draft_without_hosts_cannot_freeze(tmp_path: Path) -> None:
    assert "OPEN_API_HOSTS_MISSING" in _codes(_draft(tmp_path, profile="open_api_workspace_v1", hosts=[]))


def test_open_api_draft_with_hosts_passes_this_check(tmp_path: Path) -> None:
    codes = _codes(_draft(tmp_path, profile="open_api_workspace_v1", hosts=["api.example.org"]))
    assert "OPEN_API_HOSTS_MISSING" not in codes


def test_offline_draft_is_not_asked_for_hosts(tmp_path: Path) -> None:
    assert "OPEN_API_HOSTS_MISSING" not in _codes(_draft(tmp_path, profile="workspace_bundle_v1", hosts=[]))
