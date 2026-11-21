"""修复撞了上游的 AttributeError/ImportError 时,要把那个模块真实的公开名单给它(incident-upstream-attribute-guessing-*)。

d4(open-meteo,FlatBuffers 生成代码):构建器三轮、判官四轮都在猜生成模块的名字
(VariableWithValuesStart / StartValuesVector / …),每轮 AttributeError 换一个猜测;修复上下文只有那句报错,
没有那个模块到底导出了什么。

不变量:
  I1 upstream_module_surface(diagnostics, upstream_dir, import_module):从诊断里认出
     「module 'pkg.mod' has no attribute 'X'」/「cannot import name 'X' from 'pkg.mod'」,在钉版树里找到该模块源文件,
     静态列出顶层 def/class 名(有界,不执行代码);
  I2 找不到模块或诊断不含此类错误 → None;
  I3 修复上下文在有此发现时带 upstream_module_surface。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.ui.services import product_jobs


def _upstream(tmp_path: Path) -> Path:
    root = tmp_path / "upstream"
    (root / "anonlib").mkdir(parents=True)
    (root / "anonlib" / "__init__.py").write_text("", encoding="utf-8")
    (root / "anonlib" / "Thing.py").write_text(
        "class Thing:\n    @classmethod\n    def GetRootAs(cls, buf, offset=0):\n"
        "        return cls()\n\n"
        "def ThingStart(builder):\n    pass\n\ndef ThingAddValues(builder, v):\n    pass\n\n"
        "def ThingEnd(builder):\n    pass\n",
        encoding="utf-8",
    )
    return root


def test_an_attribute_error_on_the_upstream_yields_its_surface(tmp_path: Path) -> None:
    surface = product_jobs.upstream_module_surface(
        ("AttributeError: module 'anonlib.Thing' has no attribute 'ThingStartValuesVector' @ x.py:1",),
        _upstream(tmp_path), "anonlib",
    )
    assert surface and surface["module"] == "anonlib.Thing"
    assert "Thing" in surface["names"] and "ThingStart" in surface["names"] and "ThingEnd" in surface["names"]
    assert "ThingStartValuesVector" not in surface["names"]


def test_an_import_error_is_read_the_same_way(tmp_path: Path) -> None:
    surface = product_jobs.upstream_module_surface(
        ("ImportError: cannot import name 'ThingStartValuesVector' from 'anonlib.Thing' (/x/Thing.py)",),
        _upstream(tmp_path), "anonlib",
    )
    assert surface and surface["module"] == "anonlib.Thing" and "ThingAddValues" in surface["names"]


def test_other_diagnostics_yield_nothing(tmp_path: Path) -> None:
    upstream = _upstream(tmp_path)
    assert product_jobs.upstream_module_surface(("ValueError: nope",), upstream, "anonlib") is None
    assert product_jobs.upstream_module_surface(
        ("AttributeError: module 'json' has no attribute 'x'",), upstream, "anonlib"
    ) is None
