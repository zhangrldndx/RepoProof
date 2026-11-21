"""生产者说「夹具不对」也可能是生产者自己判错(incident-fixture-rejection-and-builder-error-routing-*)。

生产者把「output_dir 不存在」当成用户输入错误抛 UserInputError——协议要求生产者自己创建输出目录。
密封运行判 FIXTURE_REJECTED,四轮修复全发给构建器,夹具本无问题,生产者一次没修,停滞预算耗尽。

不变量:
  I1 WORKSPACE_REFERENCE_FIXTURE_REJECTED 交替路由:构建器先,再生产者,再构建器;
  I2 起草与生产者修复提示写明 output_dir 调用时不存在、必须创建、绝不当用户错误。
"""

from __future__ import annotations

from repoproof.adoption.intake import tool_drafter
from repoproof.adoption.intake.draft_selfcheck import repair_target_for


def test_fixture_rejection_alternates_builder_then_reference() -> None:
    code = "WORKSPACE_REFERENCE_FIXTURE_REJECTED"
    owners = [repair_target_for(code, round_index=i) for i in (1, 2, 3, 4)]
    assert owners == ["builder", "reference", "builder", "reference"]


def test_prompts_teach_that_the_output_directory_is_created_by_the_producer() -> None:
    for text in (tool_drafter._SYSTEM, tool_drafter._WORKSPACE_REFERENCE_REPAIR_SYSTEM):
        lowered = text.lower()
        assert "output_dir does not exist" in lowered
        assert "never a user error" in lowered or "never a userinputerror" in lowered
