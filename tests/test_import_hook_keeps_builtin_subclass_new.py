"""回执钩子不得改坏 builtins 子类的构造(incident-receipt-hook-breaks-builtin-subclass-*)。

钩子给目标模块的每个公开类换上一个记账的 __new__,闭包里存着**被包类**当时的 __new__——对没有
自定义 __new__ 的类就是 object.__new__。它的子类若同时继承 list/dict,MRO 先找到被包父类上的
记账 __new__,于是对 list 子类调用 object.__new__ → TypeError: object.__new__(X) is not safe。
上游一个公开基类 + 一个 list 子类就够触发;判官在受管子进程里用上游即炸,八次模型修复白花。

不变量:
  I1 被包基类的 list 子类能正常构造(记账 __new__ 按实际类的 MRO 找到 list.__new__);
  I2 自定义 __new__ 的类照常工作、参数原样传递;
  I3 回执照记(真实例化算调用)。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from repoproof.execution.import_hook import ENV_LEDGER, ENV_MODULE, ENV_SECRET, verify_import_receipts, write_hook_dir

_FAKEUP = '''class Base:
    pass


class Rows(Base, list):
    pass


class Special:
    def __new__(cls, value):
        instance = super().__new__(cls)
        instance.value = value
        return instance


def build():
    rows = Rows([1, 2])
    rows.append(3)
    return rows
'''


def _run_child(tmp: Path, body: str) -> tuple[subprocess.CompletedProcess, Path]:
    up = tmp / "up"
    up.mkdir(exist_ok=True)
    (up / "fakeup.py").write_text(_FAKEUP, encoding="utf-8")
    hook = write_hook_dir(tmp / "hook")
    ledger = tmp / "ledger.jsonl"
    script = tmp / "child.py"
    script.write_text(body, encoding="utf-8")
    env = dict(
        os.environ,
        PYTHONPATH=f"{hook}{os.pathsep}{up}",
        **{ENV_MODULE: "fakeup", ENV_LEDGER: str(ledger), ENV_SECRET: "s3cr3t"},
    )
    return subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=120), ledger


def test_a_list_subclass_of_a_wrapped_base_still_constructs(tmp_path: Path) -> None:
    result, ledger = _run_child(
        tmp_path,
        "import fakeup\n"
        "assert fakeup.build() == [1, 2, 3]\n"
        "assert isinstance(fakeup.build(), list)\n"
        "special = fakeup.Special(5)\n"
        "assert special.value == 5 and type(special) is fakeup.Special\n",
    )
    assert result.returncode == 0, result.stderr[-600:]
    got = verify_import_receipts(ledger, "s3cr3t", module="fakeup", min_calls=2)
    assert got["ok"] is True and got["calls"] >= 2, got
