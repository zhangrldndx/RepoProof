"""工作区验收比的是冻结判官,不是与参考实现逐字节相同(incident-workspace-acceptance-demands-reference-bytes-*)。

d2(bokeh)phase 2:Agent 的实现两轮 40 次模型调用,公开测试一直 4/5 失败——
「golden mismatch differing=['index.html']」「differing=['app/build_dashboard.py']」:验收要求输出树与
参考实现的期望树逐字节相同,而 index.html、app/*.py 这类文件是实现者写的(模板、应用文件),
独立实现不可能逐字节相同;修复反馈只说「差在 index.html」,Agent 无从下手。冻结判官(自检已证明有判别力、
绑定对照、回执)才是内容的尺子;字节同一只在同一实现跑两次时可满足(确定性测试)。

不变量:
  I1 生成的公开验收 test_example_N 走 _run_case(..., exact=False)(冻结判官 + 桩台账 + 金丝雀);
  I2 held 样例同理;
  I3 test_workspace_output_is_deterministic 仍以 _golden_sha 比同一实现两次运行;
  I4 test_workspace_runtime_smoke 不变。
"""

from __future__ import annotations

from repoproof.adoption.assembly.workspace_tool_assembler import WorkspaceGoldenExampleV1, _test_source


def _example(example_id: str) -> WorkspaceGoldenExampleV1:
    return WorkspaceGoldenExampleV1.model_validate({
        "example_id": example_id, "input_path": f"workspace-inputs/{example_id}",
        "expected_dir": f"workspace-expected/{example_id}", "truth_provenance": "UPSTREAM_DERIVED_USER_CONFIRMED",
        "truth_binding_sha256": "a" * 64,
    })


def test_public_examples_are_judged_not_byte_compared() -> None:
    source = _test_source([_example("ex1"), _example("ex2")], held=False, smoke_command=("./run.sh",))
    assert "_run_case(tmp_path, 'ex1', exact=False)" in source
    assert "_run_case(tmp_path, 'ex2', exact=False)" in source
    assert "def test_workspace_output_is_deterministic" in source
    assert "_golden_sha(first) == _golden_sha(second)" in source
    assert "def test_workspace_runtime_smoke" in source


def test_held_examples_keep_the_judge() -> None:
    source = _test_source([_example("hx")], held=True)
    assert "_run_case(tmp_path, 'hx', exact=False)" in source

# ---- 第二起(plotly d1,phase 2):字节尺子从确定性测试与烟测回来了 ----
# 这两条测试仍调用默认 exact=True 的 _run_case,它先断言与期望树金身相同再返回;Agent 一轮 20 次调用
# 全用于逐字节对齐 4 MB 的 plotly HTML,一行代码没写(incident-workspace-acceptance-demands-reference-bytes-plotly-v1)。
#   I4 生成源里每一处 _run_case 调用都带 exact=False;确定性只比同一实现两次运行;烟测只要判官接受的工作区。


def test_no_generated_call_keeps_the_byte_ruler() -> None:
    import re

    source = _test_source([_example("ex1")], held=False, smoke_command=("./run.sh",))
    calls = re.findall(r"(?<!def )_run_case\([^\n]*\)", source)
    assert calls, "no _run_case calls generated"
    offenders = [call for call in calls if "exact=False" not in call]
    assert offenders == [], offenders
    assert "_golden_sha(first) == _golden_sha(second)" in source
