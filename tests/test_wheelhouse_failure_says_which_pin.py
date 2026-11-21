"""wheelhouse 建不起来要说出是哪个 pin、pip 怎么答的(incident-wheelhouse-failure-without-pip-words-*)。

d4:tool add 以 CLI_UNCAUGHT_EXCEPTION + REFERENCE_WHEELHOUSE_MATERIALIZATION_ERROR 终止,payload 里
只有一句「参考依赖 wheelhouse 建立失败」——pin 是什么、pip 说了什么,都留在被丢掉的 stderr 里。

不变量:
  I1 pip download 非零退出 → 异常消息带决定性的一行(No matching distribution / ERROR),
     diagnostics 带 pins 与 stderr 尾行;
  I2 CLI 未捕获异常的 payload 带 diagnostics(有界)。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repoproof import cli
from repoproof.adoption.intake import example_proposer


def test_the_failure_carries_pins_and_pips_words(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "reference.lock.txt"
    lock.write_text("# derived\nanon-sdk==0.0.0\n", encoding="utf-8")

    def fake_run(argv, **_kw):
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="Looking in indexes: https://pypi.org/simple\n"
            "ERROR: Could not find a version that satisfies the requirement anon-sdk==0.0.0\n"
            "ERROR: No matching distribution found for anon-sdk==0.0.0\n",
        )

    monkeypatch.setattr(example_proposer.subprocess, "run", fake_run)
    with pytest.raises(example_proposer.ReferenceWheelhouseMaterializationError) as caught:
        example_proposer.ensure_reference_wheelhouse(lock, cache_root=tmp_path / "cache")
    message = str(caught.value)
    assert "No matching distribution found for anon-sdk==0.0.0" in message
    rows = caught.value.diagnostics
    assert rows[0] == "pins: anon-sdk==0.0.0"
    assert any("No matching distribution" in row for row in rows)


def test_the_cli_payload_carries_the_diagnostics(monkeypatch, capsys) -> None:
    error = RuntimeError("boom")
    error.diagnostics = ["pins: anon==1", "ERROR: nope"]

    def explode(_argv):
        raise error

    monkeypatch.setattr(cli, "_dispatch", explode)
    assert cli.main(["tool", "add"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason_codes"] == ["CLI_UNCAUGHT_EXCEPTION", "RUNTIME_ERROR"]
    assert payload["diagnostics"] == ["pins: anon==1", "ERROR: nope"]
