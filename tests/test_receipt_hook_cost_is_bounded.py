"""回执钩子的每次调用成本必须有界(incident-receipt-hook-unbounded-per-call-cost-*)。

d8(geojson):判官五轮超时,H32 的栈显示子进程卡在 hook/sitecustomize.py 的 _emit/_record/_new
——每次上游类实例化都要 repr 全部参数、json.dumps、hmac、open/append/close 写一行;
dict 子类的上游对象在 json 编码时又层层实例化,回执成本随数据量与调用数一起爆炸,
120 秒内连三四个 feature 的判官都跑不完。

不变量:
  I1 同一符号的逐条回执最多 _RECEIPT_LINE_CAP 条,之后只计数,退出时写一条 call_summary(count);
  I2 verify_import_receipts 把 call_summary 的 count 计入 calls,总数不失真;
  I3 参数摘要有界(reprlib),大参数不拖慢;
  I4 少量调用(< cap)的行为与从前完全一致(逐条回执)。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from repoproof.execution import import_hook
from repoproof.execution.import_hook import ENV_LEDGER, ENV_MODULE, ENV_SECRET, verify_import_receipts, write_hook_dir

_UPSTREAM = '''class Feature(dict):
    def __init__(self, payload=None):
        super().__init__(payload or {})


def make(payload):
    return Feature(payload)
'''


def _run_child(tmp: Path, body: str) -> tuple[subprocess.CompletedProcess, Path, float]:
    upstream = tmp / "upstream"
    upstream.mkdir()
    (upstream / "anonlib.py").write_text(_UPSTREAM, encoding="utf-8")
    hook = write_hook_dir(tmp / "hook")
    ledger = tmp / "receipts.jsonl"
    script = tmp / "child.py"
    script.write_text(body, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": f"{hook}{os.pathsep}{upstream}", ENV_MODULE: "anonlib",
           ENV_LEDGER: str(ledger), ENV_SECRET: "s" * 32}
    started = time.monotonic()
    completed = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=300)
    return completed, ledger, time.monotonic() - started


def test_many_calls_with_big_arguments_stay_cheap_and_countable(tmp_path: Path) -> None:
    body = '''import anonlib
big = {"coordinates": list(range(20000))}
for _ in range(3000):
    anonlib.make(big)
print("done")
'''
    completed, ledger, elapsed = _run_child(tmp_path, body)
    assert completed.returncode == 0, completed.stderr[-800:]
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 2 * import_hook._RECEIPT_LINE_CAP + 4, len(lines)
    receipts = verify_import_receipts(ledger, "s" * 32, module="anonlib", min_calls=1)
    assert receipts["ok"], receipts
    assert receipts["calls"] == 6000, receipts  # make() plus Feature.__new__ per iteration
    assert elapsed < 60, elapsed


def test_few_calls_are_still_receipted_one_by_one(tmp_path: Path) -> None:
    completed, ledger, _ = _run_child(tmp_path, "import anonlib\nfor _ in range(3):\n    anonlib.make({'a': 1})\n")
    assert completed.returncode == 0, completed.stderr[-800:]
    receipts = verify_import_receipts(ledger, "s" * 32, module="anonlib", min_calls=1)
    assert receipts["ok"] and receipts["calls"] == 6
    assert sum(1 for line in ledger.read_text(encoding="utf-8").splitlines() if '"call"' in line) == 6


# ---- 第二起(同一上游,彩排正控):参数摘要 repr 了用户对象,对象的 __repr__ 又调回被包的函数 ----
# geojson 对象的 __repr__ 走 dumps → GeoJSONEncoder → to_mapping,这些都被量具包着,每次 _record 又
# 对参数 repr 一次……PyObject_Repr 递归,一次工具调用跑了几分钟(sample 可见)。
#   I5 参数摘要不调用任何用户定义的 __repr__:内建标量有界 repr,容器只记类型与长度,其余只记类型名;
#   I6 摘要期间触发的嵌套调用不再记账(重入保护)。



def test_a_repr_that_calls_hooked_code_does_not_explode(tmp_path: Path) -> None:
    body = '''import anonlib
from anonlib import Feature

class Shape(Feature):
    def __repr__(self):
        return anonlib.dumps(self)

shapes = [Shape({"i": i, "coords": list(range(200))}) for i in range(300)]
for s in shapes:
    anonlib.make(s)
print("done")
'''
    upstream_extra = """

def dumps(obj):
    return "{" + ",".join(str(k) for k in obj) + "}"
"""
    completed, ledger, elapsed = _run_child_with_upstream(tmp_path, body, _UPSTREAM + upstream_extra)
    assert completed.returncode == 0, completed.stderr[-800:]
    assert elapsed < 30, elapsed
    receipts = verify_import_receipts(ledger, "s" * 32, module="anonlib", min_calls=1)
    assert receipts["ok"] and receipts["calls"] >= 300
    # The digest never ran the object's __repr__, so the hooked dumps() it
    # would call was never receipted: nothing inside the digest counts.
    symbols = [json.loads(line)["p"].get("symbol") for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert "anonlib.dumps" not in symbols, symbols[:20]


def _run_child_with_upstream(tmp: Path, body: str, upstream_source: str):
    upstream = tmp / "upstream"
    upstream.mkdir()
    (upstream / "anonlib.py").write_text(upstream_source, encoding="utf-8")
    hook = write_hook_dir(tmp / "hook")
    ledger = tmp / "receipts.jsonl"
    script = tmp / "child.py"
    script.write_text(body, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": f"{hook}{os.pathsep}{upstream}", ENV_MODULE: "anonlib",
           ENV_LEDGER: str(ledger), ENV_SECRET: "s" * 32}
    started = time.monotonic()
    completed = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=300)
    return completed, ledger, time.monotonic() - started
