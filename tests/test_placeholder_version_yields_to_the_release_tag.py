"""占位版本不是版本:0.0.0 不得压过与冻结 commit 一致的发布 tag(incident-placeholder-version-outranks-tag-*)。

同一 SDK 仓库第四站:发行版推出来了,python/pyproject.toml 却写着 version = "0.0.0"(semantic-release
在发版时盖章,仓库里永远是占位),派生把它当真 → 锁 dist==0.0.0 → pip 找不到 → tool add 未捕获异常。
`__version__ = "unknown"` 早已按「不是可安装发行版」处理;pyproject/setup.cfg/PKG-INFO 的占位是同一件事。

不变量:
  I1 is_placeholder_version:0.0.0 / 0.0 / 0 / 0.0.0.dev0 / unknown / 0+unknown → True;1.2.3 / 0.1.0 → False;
  I2 pyproject(根目录或子目录)声明占位、且发布 tag 指向冻结 commit → 用 tag 的版本;
  I3 只有占位、没有 tag → 返回空(派生不出),而不是 0.0.0。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from repoproof.adoption.intake.upstream_pin import is_placeholder_version, upstream_version


def test_placeholders_are_recognised() -> None:
    for value in ("0.0.0", "0.0", "0", "0.0.0.dev0", "0.0.0dev", "unknown", "0+unknown", "UNKNOWN", "dynamic"):
        assert is_placeholder_version(value), value
    for value in ("1.2.3", "0.1.0", "0.0.1", "2024.1", "1.0.0.dev3"):
        assert not is_placeholder_version(value), value


def _repo(tmp_path: Path, *, version: str, tag: str | None) -> tuple[Path, str]:
    root = tmp_path / "upstream"
    (root / "python").mkdir(parents=True)
    (root / "python" / "pyproject.toml").write_text(
        f'[project]\nname = "anon-sdk"\nversion = "{version}"\n', encoding="utf-8"
    )
    (root / "package.json").write_text("{}", encoding="utf-8")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
           "HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "."], cwd=root, check=True, env=env)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"], cwd=root, check=True, env=env)
    if tag:
        subprocess.run(["git", "tag", tag], cwd=root, check=True, env=env)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, env=env,
                            capture_output=True, text=True).stdout.strip()
    return root, commit


def test_a_placeholder_pyproject_yields_to_the_tag(tmp_path: Path) -> None:
    root, commit = _repo(tmp_path, version="0.0.0", tag="v1.28.0")
    version = upstream_version(root, distribution="anon-sdk", requested_revision="v1.28.0", resolved_commit=commit)
    assert version == "1.28.0"


def test_a_placeholder_without_a_tag_is_underivable(tmp_path: Path) -> None:
    root, commit = _repo(tmp_path, version="0.0.0", tag=None)
    assert upstream_version(root, distribution="anon-sdk", requested_revision="main", resolved_commit=commit) == ""


def test_a_real_declared_version_still_wins(tmp_path: Path) -> None:
    root, commit = _repo(tmp_path, version="2.5.0", tag="v9.9.9")
    version = upstream_version(root, distribution="anon-sdk", requested_revision="v9.9.9", resolved_commit=commit)
    assert version == "2.5.0"
