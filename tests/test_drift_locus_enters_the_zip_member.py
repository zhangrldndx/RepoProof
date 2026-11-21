"""漂移定位要进到 zip 成员里面,点到行(incident-drift-locus-stops-at-the-zip-member-*)。

d5(ebooklib)attempt-5:四轮「kindle_weekly.epub=BYTES_DIFFER@EPUB/content.opf」,生产者改写四次原话不变——
普通文本文件的 locus 会点到「line N: <摘录>」,zip 容器只点到成员名;成员里哪一行在漂(上游写入的
dcterms:modified 时间戳)修复方看不到。

不变量:
  I1 zip 容器内第一个不同的成员若是 UTF-8 文本,locus = "<member>: line N: <实际侧摘录>";
  I2 摘录只来自实际侧(生产者这次跑出来的),绝不回显期望侧;
  I3 二进制成员或一侧独有的成员仍只点名成员。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from repoproof.execution.workspace_bundle import _divergence_locus


def _zip(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members:
            archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), payload)
    return buffer.getvalue()


def test_a_text_member_names_its_differing_line(tmp_path: Path) -> None:
    actual = tmp_path / "a.epub"
    expected = tmp_path / "e.epub"
    actual.write_bytes(_zip([
        ("mimetype", b"application/epub+zip"),
        ("EPUB/content.opf", b"<package>\n<metadata>\n<meta property='dcterms:modified'>2026-09-06T08:07:12Z</meta>\n"
                             b"</metadata>\n</package>\n"),
    ]))
    expected.write_bytes(_zip([
        ("mimetype", b"application/epub+zip"),
        ("EPUB/content.opf", b"<package>\n<metadata>\n<meta property='dcterms:modified'>2026-09-06T08:07:09Z</meta>\n"
                             b"</metadata>\n</package>\n"),
    ]))
    locus = _divergence_locus(actual, expected)
    assert locus.startswith("EPUB/content.opf: line 3: ")
    assert "2026-09-06T08:07:12Z" in locus and "08:07:09Z" not in locus


def test_binary_and_one_sided_members_stay_member_only(tmp_path: Path) -> None:
    actual = tmp_path / "a.zip"
    expected = tmp_path / "e.zip"
    actual.write_bytes(_zip([("img.bin", b"\x00\x01\x02\xff"), ("same.txt", b"x")]))
    expected.write_bytes(_zip([("img.bin", b"\x00\x01\x03\xff"), ("same.txt", b"x")]))
    assert _divergence_locus(actual, expected) == "img.bin"
    actual.write_bytes(_zip([("only-here.txt", b"x")]))
    expected.write_bytes(_zip([("same.txt", b"x")]))
    assert _divergence_locus(actual, expected) == "only-here.txt (one side only)"
