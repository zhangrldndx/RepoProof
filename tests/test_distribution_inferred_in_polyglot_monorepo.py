"""多语言单仓的发行版名要能在 Python 子目录里找到(incident-distribution-not-inferred-in-monorepo-*)。

同一 SDK 仓库第三站:版本派生(子目录 pyproject 同名才算)与导入包推导(python/<pkg>)都已学会
子目录布局,但两者都以 distribution 为前提——而 extract_distribution 只看根目录,根目录只有
package.json/Package.swift/build.gradle,于是 distribution=''、import_module='',两处子目录支持
从未被触发,自检第 1 轮 DEPENDENCY_LOCK_MISSING(HARNESS 终态,无修复路径)。

不变量:
  I1 根目录没有 Python 元数据、恰有一个一级子目录带 pyproject [project]/[tool.poetry] name → 采用,
     证据写明子目录;
  I2 由此推出的 distribution 让 extract_import_module 在该子目录找到包;
  I3 多个子目录都带 pyproject(歧义)→ 不猜,原因列出候选;
  I4 根目录有 pyproject 时行为不变(根目录优先)。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.tool_intake import extract_distribution, extract_import_module


def _checkout(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "upstream"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


_PY = 'project = {name = "anon-sdk", version = "1.2.3"}\n'


def test_a_python_subdirectory_names_the_distribution(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {
        "package.json": "{}", "Package.swift": "// swift", "build.gradle.kts": "",
        "python/pyproject.toml": "[project]\nname = \"anon-sdk\"\nversion = \"1.2.3\"\n",
        "python/anon_sdk/__init__.py": "",
        "ts/package.json": "{}",
    })
    dist, evidence = extract_distribution(root)
    assert dist == "anon-sdk"
    assert "python/" in evidence
    module, why = extract_import_module(root, dist)
    assert module == "anon_sdk", why


def test_two_candidate_subdirectories_are_ambiguous_and_named(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {
        "python/pyproject.toml": "[project]\nname = \"anon-sdk\"\n",
        "bindings/pyproject.toml": "[project]\nname = \"anon-bindings\"\n",
    })
    dist, evidence = extract_distribution(root)
    assert dist == ""
    assert "python/" in evidence and "bindings/" in evidence


def test_the_root_pyproject_still_wins(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {
        "pyproject.toml": "[project]\nname = \"root-dist\"\n",
        "python/pyproject.toml": "[project]\nname = \"anon-sdk\"\n",
    })
    assert extract_distribution(root)[0] == "root-dist"
