"""「没观察到上游调用」要说出量到了什么、什么不算(incident-upstream-call-marker-without-counts-*)。

d1(plotly)attempt-17:判官只 `import plotly; plotly.__version__`——属性读不是调用;
四轮 UPSTREAM_CALL_NOT_OBSERVED 判官改写四次原话不变。d4(open-meteo)attempt-11 第 2–7 轮同样只见这句裸标记。
回执钩子明明数了 imports/calls,标记却不说;判官不知道「什么算一次调用」。

不变量:
  I1 upstream_call_marker_detail(imports, calls):写出 observed imports=N calls=M,
     并说明 import 与属性读(module.__version__)不算,须调用上游的函数/方法且判决依赖其返回值;
  I2 判官修复教学写明同一条规则。
"""

from __future__ import annotations

from repoproof.adoption.intake import tool_drafter
from repoproof.verification.workspace_semantic import upstream_call_marker_detail


def test_the_marker_carries_the_counts_and_the_rule() -> None:
    detail = upstream_call_marker_detail(imports=1, calls=0)
    assert "imports=1" in detail and "calls=0" in detail
    assert "attribute" in detail and "__version__" in detail
    assert "call" in detail and "return" in detail


def test_the_repair_teaching_states_what_counts() -> None:
    text = tool_drafter._VERIFIER_REPAIR_SYSTEM
    assert "attribute read" in text or "attribute reads" in text
    assert "__version__" in text
