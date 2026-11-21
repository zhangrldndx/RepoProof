"""判官超时要说出卡在哪一行、哪个对照、多少秒(incident-verifier-timeout-without-location-*)。

d8(geojson):判官五轮 TimeoutExpired,verifier 被盲改四次,失败原话逐字未变——「semantic verifier
execution failed: TimeoutExpired」既不说超时秒数、不说是哪个对照(normal / counterfactual),更不说
子进程当时在哪一行;夹具只有三四个 feature,120 秒的超时不可能是数据量,可没有栈就无从下手。

不变量:
  I1 runner 在预算将尽时(faulthandler)把 Python 栈倒进 stderr 并退出;
  I2 无论是子进程自己倒栈退出还是父进程 TimeoutExpired,错误都是 SemanticVerifierError,消息带
     超时秒数与对照名,diagnostics 带栈帧尾行(文件:行:函数);
  I3 正常的判官不受影响。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repoproof.verification.semantic_artifact import SemanticVerifierError, screen_semantic_candidate

_HANGING = '''import time
from pathlib import Path

import minishout


def _wait_forever():
    time.sleep(60)


def verify(input_path: Path, artifact_path: Path) -> dict:
    minishout.shout("x")
    _wait_forever()
    return {"ok": True, "reason_codes": [], "checked_commitment_ids": ["transform-input"]}
'''


def _world(tmp_path: Path) -> dict:
    upstream = tmp_path / "upstream"
    upstream.mkdir(parents=True)
    (upstream / "minishout.py").write_text("def shout(text):\n    return text.upper()\n", encoding="utf-8")
    verifier = tmp_path / "semantic_verifier.py"
    verifier.write_text(_HANGING, encoding="utf-8")
    (tmp_path / "input.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "artifact.txt").write_text("HELLO", encoding="utf-8")
    return {"upstream": upstream, "verifier": verifier, "input": tmp_path / "input.txt",
            "artifact": tmp_path / "artifact.txt"}


def test_a_hanging_verifier_reports_where_it_hung(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with pytest.raises(SemanticVerifierError) as caught:
        screen_semantic_candidate(
            verifier_source=world["verifier"], input_path=world["input"], artifact_path=world["artifact"],
            python_exe=sys.executable, upstream_dir=world["upstream"], import_module="minishout",
            required_commitment_ids=["transform-input"], isolation_required=False, timeout_s=4,
        )
    message = str(caught.value)
    assert "TimeoutExpired" in message and "4" in message and "normal" in message, message
    frames = " ".join(getattr(caught.value, "diagnostics", ()) or ())
    assert "_wait_forever" in frames or "time.sleep" in frames or "semantic_verifier.py" in frames, frames
