"""PDF 交付物必须能显示用户自己的文字;显示不了是交付形态的边界(incident-pdf-cannot-render-input-script-*)。

d3(fpdf2):用户配置里的成员名是中文;密封运行里没有任何 CJK 字体(上游不带、系统字体不可移植),
生产者先撞 helvetica 异常,再试图用 fontTools 现造一枚字体;判官抽 PDF 文字找不到「孩子学校」,
十一轮谁也修不好——这不是谁写错了,是 PDF 这种交付形态在没有字体时装不下用户的文字。

不变量(不依赖 PDF 文本抽取库;看字体资源):
  I1 pdf_missing_input_script(pdf, input_texts):输入里含非拉丁文字(CJK 等)而 PDF 的字体只有 14 种核心 Type1
     (没有任何嵌入的 TrueType/Type0/Type3 字体)→ 返回装不下的样本;输入只有 ASCII、或 PDF 嵌入了字体 → 空;
  I2 该发现投影为 WorkspaceBundleError(PDF_CANNOT_RENDER_INPUT_SCRIPT),owner CONTRACT、不派模型修,
     进 OUTPUT_FORM 降级提案(改交付 HTML 打印页,浏览器提供字体)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.intake import draft_selfcheck
from repoproof.adoption.intake.workspace_fixtures import assert_pdf_shows_input_script, pdf_missing_input_script
from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import product_jobs

_MINIMAL_PDF = b"\n".join([
    b"%PDF-1.4",
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R "
    b"/Resources << /Font << /F1 5 0 R >> >> >> endobj",
    b"4 0 obj << /Length 44 >> stream",
    b"BT /F1 12 Tf 10 50 Td (Hello wall) Tj ET",
    b"endstream endobj",
    b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
    b"xref",
    b"0 6",
    b"0000000000 65535 f",
    b"trailer << /Root 1 0 R /Size 6 >>",
    b"startxref",
    b"0",
    b"%%EOF",
    b"",
])


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "wall.pdf"
    path.write_bytes(_MINIMAL_PDF)
    return path


def test_cjk_input_with_core_fonts_only_is_reported(tmp_path: Path) -> None:
    missing = pdf_missing_input_script(_pdf(tmp_path), ["孩子学校", "我的排班", "Hello"])
    assert missing and "孩子学校" in missing
    assert pdf_missing_input_script(_pdf(tmp_path), ["Hello", "wall"]) == []
    embedded = tmp_path / "embedded.pdf"
    embedded.write_bytes(_MINIMAL_PDF.replace(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /TrueType /BaseFont /AnonSans "
        b"/FontDescriptor << /FontFile2 9 0 R >> >>",
    ))
    assert pdf_missing_input_script(embedded, ["孩子学校"]) == []


def test_the_finding_is_an_output_form_boundary(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceBundleError) as caught:
        assert_pdf_shows_input_script(_pdf(tmp_path), ["孩子学校"], relative="wall.pdf")
    assert caught.value.code == "PDF_CANNOT_RENDER_INPUT_SCRIPT"
    assert any("wall.pdf" in row and "孩子学校" in row for row in caught.value.diagnostics)
    assert product_jobs._workspace_fixture_failure_owner("PDF_CANNOT_RENDER_INPUT_SCRIPT") == "CONTRACT"
    assert draft_selfcheck.repair_target_for("PDF_CANNOT_RENDER_INPUT_SCRIPT", round_index=1) is None
    proposal = draft_selfcheck.output_form_downgrade_proposal(
        ("PDF_CANNOT_RENDER_INPUT_SCRIPT: wall.pdf lacks 孩子学校",)
    )
    assert proposal and proposal["kind"] == "OUTPUT_FORM"
