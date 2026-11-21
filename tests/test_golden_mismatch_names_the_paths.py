"""验收失败要说出是哪些文件(incident-golden-mismatch-unlocated-*)。

一趟彩排的正控在三个样例上都失败,断言只留下两串 sha256——运行会话随即被清理,没有任何
东西告诉你差在哪个文件。失败要说出在哪。公开验收改由冻结判官裁定后(H56),字节比对只剩
确定性测试(同一实现跑两次),它的断言消息同样点名文件;判官拒绝时消息带原因码与原话。

不变量:
  I1 两棵树不一致时,_golden_mismatch 点名多出的、缺少的、内容不同的路径(有界);确定性断言用它;
  I2 判官拒绝时,验收消息带原因码与判官原话;
  I3 一致且判官通过时行为不变(通过)。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

from repoproof.adoption.assembly import workspace_tool_assembler as asm

_FAKE_TOOL = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import sys
    from pathlib import Path
    out = Path(sys.argv[3]); out.mkdir()
    (out / "README.md").write_text("items=2\\n")
    (out / "data.json").write_text('{"n": 2}\\n')
    """
)


def _world(root: Path, *, readme: str) -> Path:
    example = root / "fixtures" / "example-1"
    (example / "input").mkdir(parents=True)
    (example / "input" / "in.txt").write_text("x", encoding="utf-8")
    (example / "expected").mkdir()
    (example / "expected" / "README.md").write_text(readme, encoding="utf-8")
    (example / "expected" / "data.json").write_text('{"n": 2}\n', encoding="utf-8")
    module = root / "test_public_contract.py"
    module.write_text(asm._test_source([SimpleNamespace(example_id="example-1")], held=False), encoding="utf-8")
    (root / "semantic_verifier.py").write_text(
        "from pathlib import Path\n\n\n"
        "def verify(input_path, artifact_path):\n"
        "    text = (Path(artifact_path) / 'README.md').read_text(encoding='utf-8')\n"
        "    ok = text == 'items=2\\n'\n"
        "    return {'ok': ok, 'reason_codes': [] if ok else ['README_MISMATCH'],\n"
        "            'checked_commitment_ids': ['c1'],\n"
        "            'reason_details': {} if ok else\n"
        "                {'README_MISMATCH': 'README.md expected items=2 observed ' + text.strip()}}\n",
        encoding="utf-8",
    )
    tool = root / "fake-tool"
    tool.write_text(_FAKE_TOOL, encoding="utf-8")
    tool.chmod(0o755)
    return module


def _pytest(module: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "REPOPROOF_TOOL_BIN": str(module.parent / "fake-tool")}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "-o", "addopts=",
         str(module), "-k", "test_example_1"],
        capture_output=True, text=True, env=env, cwd=module.parent, timeout=120,
    )


def test_a_mismatch_names_the_differing_file(tmp_path: Path) -> None:
    prelude = asm._TEST_PRELUDE.replace('os.environ["REPOPROOF_TOOL_BIN"]', "'x'")
    namespace: dict = {"__file__": str(tmp_path / "test_public_contract.py")}
    exec(prelude, namespace)  # noqa: S102 - the generated acceptance prelude, byte for byte
    ours, theirs = tmp_path / "ours", tmp_path / "theirs"
    for root, readme in ((ours, "items=3\n"), (theirs, "items=2\n")):
        root.mkdir()
        (root / "README.md").write_text(readme, encoding="utf-8")
        (root / "data.json").write_text('{"n": 2}\n', encoding="utf-8")
    message = namespace["_golden_mismatch"](ours, theirs)
    assert "README.md" in message and "data.json" not in message.split("differing")[-1]


def test_a_judge_rejection_names_the_reason(tmp_path: Path) -> None:
    # The fake tool writes items=2; a judge expecting that passes, one expecting
    # items=3 does not — and the acceptance says why, not just that it failed.
    module = _world(tmp_path, readme="items=2\n")
    (module.parent / "semantic_verifier.py").write_text(
        (module.parent / "semantic_verifier.py").read_text(encoding="utf-8").replace("items=2", "items=3"),
        encoding="utf-8",
    )
    result = _pytest(module)
    assert result.returncode != 0
    assert "README_MISMATCH" in result.stdout, result.stdout
    assert "observed items=2" in result.stdout, result.stdout


def test_a_match_still_passes(tmp_path: Path) -> None:
    result = _pytest(_world(tmp_path, readme="items=2\n"))
    assert result.returncode == 0, result.stdout + result.stderr
