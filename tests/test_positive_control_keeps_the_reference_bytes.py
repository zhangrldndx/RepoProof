"""正控不得改写参考实现的字节;参考实现不得从自己的源码派生交付物(incident-positive-control-mutates-reference-*)。

一趟彩排正控在三个样例上金样不一致。参考实现用 Path(__file__).read_text() 把自己写成交付的 app.py;
宿主把参考实现改装成暂存协议适配器时在文件末尾追加了一段桥接代码——于是 __file__ 读到的
不再是冻结时的字节,app.py 变了。密封自检里的文件叫 reference_impl.py、内容原样,所以那边通过。

不变量:
  I1 正控由两个文件构成:impl_reference.py 与冻结参考实现逐字节相同;impl.py 是只做协议桥接的适配器,
     导入前者而不改写它;
  I2 参考实现读取自身源码(__file__、inspect.getsource)是静态策略错误 REFERENCE_READS_ITS_OWN_SOURCE,
     有修复路线(把应用文件写成字面量);干净的源码不报;
  I3 起草/修复提示写明这条规则。
"""

from __future__ import annotations

from repoproof.adoption.intake import tool_drafter
from repoproof.runner import tool_host_bridge

_REFERENCE = (
    "from pathlib import Path\n"
    "class UserInputError(ValueError):\n    pass\n"
    "def build_workspace(input_path: Path, output_dir: Path) -> None:\n"
    "    output_dir.mkdir()\n"
    "    (output_dir / 'app.py').write_text(Path(__file__).read_text())\n"
)


def test_the_positive_control_is_an_adapter_over_the_verbatim_reference() -> None:
    files = tool_host_bridge._workspace_reference_control_files(_REFERENCE)
    assert set(files) == {"impl.py", "impl_reference.py"}
    assert files["impl_reference.py"] == _REFERENCE, "参考实现逐字节不动"
    adapter = files["impl.py"]
    assert "impl_reference" in adapter and "def build_workspace" in adapter
    assert "_reference.build_workspace(" in adapter, "桥接只转发,不重写"
    assert "read_text(" not in adapter, "适配器自己不读任何源码"


def test_reading_own_source_is_a_named_policy_error() -> None:
    errors = tool_drafter.reference_source_policy_errors(_REFERENCE, function_name="build_workspace")
    assert "REFERENCE_READS_ITS_OWN_SOURCE" in errors
    clean = _REFERENCE.replace("Path(__file__).read_text()", "'print(1)'")
    assert "REFERENCE_READS_ITS_OWN_SOURCE" not in tool_drafter.reference_source_policy_errors(
        clean, function_name="build_workspace"
    )
    via_inspect = _REFERENCE.replace("Path(__file__).read_text()", "__import__('inspect').getsource(build_workspace)")
    assert "REFERENCE_READS_ITS_OWN_SOURCE" in tool_drafter.reference_source_policy_errors(
        via_inspect, function_name="build_workspace"
    )


def test_the_prompts_teach_the_rule() -> None:
    for text in (tool_drafter._SYSTEM, tool_drafter._WORKSPACE_REFERENCE_REPAIR_SYSTEM):
        assert "__file__" in text and "literal" in text.lower()
