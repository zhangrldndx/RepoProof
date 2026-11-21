"""回执钩子要真的进到工具子进程(incident-receipt-hook-never-reaches-the-tool-process-*)。

宿主把钩子经 PYTHONPATH 注入判卷环境,意在进工具子进程;交付工具的 bin 脚本却
exec env PYTHONPATH=$ROOT/src 整个覆盖了它——生产者从未带钩子,回执历来来自工作区自己的
smoke 运行。一个运行期不调上游的应用就让 oracle 5/5 通过的正控被判「装样子 import」。

不变量:
  I1 bin 脚本保留 Harness 命名通道 REPOPROOF_EXTRA_PYTHONPATH:带它时工具子进程加载该目录的 sitecustomize;
  I2 不带它时普通 PYTHONPATH 仍被隔离(交付期语义不变);
  I3 宿主的钩子环境同时注入 REPOPROOF_EXTRA_PYTHONPATH=钩子目录。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from repoproof.adoption.assembly import workspace_tool_assembler as asm
from repoproof.runner import host_guided


def _skeleton(tmp_path: Path) -> Path:
    root = tmp_path / "tool"
    (root / "bin").mkdir(parents=True)
    (root / "src" / "anon_tool").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, root / ".venv" / "bin" / "python")
    (root / "src" / "anon_tool" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "anon_tool" / "__main__.py").write_text(
        "import sys\nprint('hooked' if 'rp_marker' in sys.modules else 'plain')\n", encoding="utf-8"
    )
    script = root / "bin" / "anon-tool"
    script.write_text(asm._BIN.format(package="anon_tool"), encoding="utf-8")
    script.chmod(0o755)
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text("import sys\nsys.modules['rp_marker'] = sys\n", encoding="utf-8")
    return root


def _run(root: Path, env: dict) -> str:
    result = subprocess.run([str(root / "bin" / "anon-tool")], capture_output=True, text=True, env=env, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_the_named_channel_reaches_the_tool_process(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    assert _run(root, {**base, "REPOPROOF_EXTRA_PYTHONPATH": str(tmp_path / "hook")}) == "hooked"


def test_plain_pythonpath_stays_isolated(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    assert _run(root, {**base, "PYTHONPATH": str(tmp_path / "hook")}) == "plain"


def test_the_host_hook_env_names_the_channel() -> None:
    assert "REPOPROOF_EXTRA_PYTHONPATH" in host_guided._HOOK_EXTRA_PATH_ENV
