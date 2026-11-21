"""密钥「必需式读取」只算运行时包里的代码(incident-secret-scan-condemns-repo-tooling-*)。

一个仓库的 contributors/ 脚本用 os.environ["GITHUB_TOKEN"] 生成贡献者页面,准入把整个仓库判成
「要求环境密钥」——可交付的能力根本不经过那个脚本。仓库级工具脚本(发布、贡献者页、基准)不是
可导入的运行时;只有 import 包目录(pkg/ 或 src/pkg/)里的读取才构成运行时需求。

不变量:
  I1 包目录之外的必需式读取 → 非运行时区(风险,不阻断);
  I2 包目录之内的必需式读取 → secrets_required(阻断);
  I3 tests/docs/examples 的旧规则不变。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.analysis.repository_analyzer import analyze_repository_dir


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_a_repo_tooling_script_does_not_make_the_package_require_a_secret(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "pkg/__init__.py": "__all__ = ['render']\n",
            "pkg/render.py": "def render():\n    return 1\n",
            "contributors/build_page.py": "import os\ntoken = os.environ['GITHUB_TOKEN']\n",
            "pyproject.toml": "[project]\nname = 'pkg'\nversion = '1.0'\n",
        },
    )
    report = analyze_repository_dir(root)
    assert [f.value for f in report.secrets_required] == []
    assert "GITHUB_TOKEN" in {f.value for f in report.secrets_test_zone}


def test_a_read_inside_the_package_is_required(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/client.py": "import os\ntoken = os.environ['API_TOKEN']\n",
            "pyproject.toml": "[project]\nname = 'pkg'\nversion = '1.0'\n",
        },
    )
    report = analyze_repository_dir(root)
    assert "API_TOKEN" in {f.value for f in report.secrets_required}


def test_src_layout_package_reads_are_required_too(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "src/pkg/__init__.py": "",
            "src/pkg/client.py": "import os\ntoken = os.environ['API_TOKEN']\n",
            "scripts/release.py": "import os\nt = os.environ['RELEASE_TOKEN']\n",
        },
    )
    report = analyze_repository_dir(root)
    assert {f.value for f in report.secrets_required} == {"API_TOKEN"}
    assert "RELEASE_TOKEN" in {f.value for f in report.secrets_test_zone}
