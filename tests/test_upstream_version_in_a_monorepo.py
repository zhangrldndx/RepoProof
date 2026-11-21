"""钉版树的版本要能在单仓多语言布局里找到,找不到时要说出找过哪里(incident-lock-missing-unlocated-*)。

一个 SDK 仓库把 Python 包放在 python/ 子目录(自带 pyproject),根目录没有 pyproject。
版本派生只看根目录 → 参考锁为空 → 自检第 1 轮 DEPENDENCY_LOCK_MISSING、零诊断、零修复。

不变量:
  I1 子目录 pyproject 的 [project].name 归一后等于发行版名 → 用它的版本;
  I2 名字不同的子目录 pyproject(诱饵)不被采用;
  I3 锁派生不出时,DEPENDENCY_LOCK_MISSING 带诊断,说出 reference.lock.txt 与找过的来源。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.upstream_pin import upstream_version
from repoproof.ui.services import product_jobs


def _checkout(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "upstream"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_a_python_subdirectory_pyproject_is_found(tmp_path: Path) -> None:
    root = _checkout(
        tmp_path,
        {
            "README.md": "polyglot",
            "python/pyproject.toml": "[project]\nname = 'anon-sdk'\nversion = '1.2.3'\n",
            "python/anon_sdk/__init__.py": "",
            "other/pyproject.toml": "[project]\nname = 'other-thing'\nversion = '9.9.9'\n",
        },
    )
    assert upstream_version(root, import_module="anon_sdk", distribution="anon-sdk") == "1.2.3"


def test_a_decoy_subdirectory_is_not_used(tmp_path: Path) -> None:
    root = _checkout(
        tmp_path,
        {"other/pyproject.toml": "[project]\nname = 'other-thing'\nversion = '9.9.9'\n"},
    )
    assert upstream_version(root, import_module="anon_sdk", distribution="anon-sdk") == ""


def test_a_missing_lock_says_where_it_looked(monkeypatch, tmp_path: Path) -> None:
    from test_import_module_inference_and_readiness import _draft

    draft_dir = _draft(tmp_path, import_module="anon")
    (draft_dir / "reference.lock.txt").unlink()
    monkeypatch.setattr(product_jobs, "_validated_draft_dir", lambda *a, **k: (draft_dir, ""))
    tmp_path = draft_dir
    monkeypatch.setattr(product_jobs, "resolved_dependency_lock", lambda *a, **k: "")
    result = product_jobs.propose_workspace_fixture_candidates(tmp_path, n=1, offline=True)
    assert result["ok"] is False and result["reason_codes"] == ["DEPENDENCY_LOCK_MISSING"]
    assert result["diagnostics"] and "reference.lock.txt" in result["diagnostics"][0]
