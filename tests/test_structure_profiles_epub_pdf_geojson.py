"""三个新的结构 profile:epub_v1 / pdf_v1 / geojson_v1(m6.4 prework 9)。

同一把尺子(portable_workspace_runtime.profile_format_error)同时供 Core 与导出的运行时
使用,所以 Core 收的,交付到用户机器上的工具也收;反之亦然。

不变量:
  I1 结构成立的文件 → None;结构不成立的 → 一个稳定公开码,永不泄漏解析器细节;
  I2 合同模型接受这三个 profile 名;
  I3 Core 的 _validate_format 对同一字节给出同一裁决(WorkspaceBundleError 带同码);
  I4 epub:mimetype 必须是首个成员且为 application/epub+zip,container.xml 指向的 OPF 必须存在并可解析;
  I5 pdf:%PDF- 头、尾部 %%EOF、至少一个页对象(或对象流);
  I6 geojson:顶层 type 合法;FeatureCollection 的 features 每个都是 Feature 且 geometry/properties 形状正确。
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from repoproof.adoption.delivery.portable_workspace_runtime import profile_format_error
from repoproof.domain.models import WorkspaceArtifactRule
from repoproof.execution.workspace_bundle import WorkspaceBundleError, _validate_format

_OPF = (
    b'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
    b"<metadata/><manifest/><spine/></package>"
)
_CONTAINER = (
    b'<?xml version="1.0"?>'
    b'<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    b'<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
    b"</rootfiles></container>"
)


def _epub(
    *, mimetype: bytes = b"application/epub+zip", first: bool = True, container: bool = True, opf: bool = True
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if first:
            archive.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        if container:
            archive.writestr("META-INF/container.xml", _CONTAINER)
        if opf:
            archive.writestr("OEBPS/content.opf", _OPF)
        archive.writestr("OEBPS/chapter1.xhtml", b"<html/>")
        if not first:
            archive.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()


def _pdf(
    *,
    header: bytes = b"%PDF-1.4\n",
    page: bytes = b"1 0 obj << /Type /Page >> endobj\n",
    eof: bytes = b"%%EOF\n",
) -> bytes:
    return header + b"%\xe2\xe3\xcf\xd3\n" + page + b"trailer << /Root 1 0 R >>\n" + eof


def _check(tmp_path: Path, profile: str, payload: bytes) -> str | None:
    path = tmp_path / f"artifact.{profile.split('_')[0]}"
    path.write_bytes(payload)
    return profile_format_error(profile, path, payload)


@pytest.mark.parametrize(
    "payload",
    [_epub(), _epub(container=True)],
)
def test_a_well_formed_epub_passes(tmp_path: Path, payload: bytes) -> None:
    assert _check(tmp_path, "epub_v1", payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        _epub(mimetype=b"application/zip"),
        _epub(first=False),
        _epub(container=False),
        _epub(opf=False),
        b"not a zip at all",
    ],
)
def test_a_broken_epub_is_named_by_one_code(tmp_path: Path, payload: bytes) -> None:
    assert _check(tmp_path, "epub_v1", payload) == "WORKSPACE_FORMAT_EPUB_INVALID"


def test_a_well_formed_pdf_passes(tmp_path: Path) -> None:
    assert _check(tmp_path, "pdf_v1", _pdf()) is None
    assert _check(tmp_path, "pdf_v1", _pdf(page=b"2 0 obj << /Type /ObjStm >> endobj\n")) is None


@pytest.mark.parametrize(
    "payload",
    [_pdf(header=b"PDF-1.4\n"), _pdf(eof=b""), _pdf(page=b""), b"%PDF-1.7\n" + b"x" * 8 + b"\n%%EOF\n"],
)
def test_a_broken_pdf_is_named_by_one_code(tmp_path: Path, payload: bytes) -> None:
    assert _check(tmp_path, "pdf_v1", payload) == "WORKSPACE_FORMAT_PDF_INVALID"


def _collection(features: list[dict]) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": features}).encode("utf-8")


_POINT = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [139.7, 35.7]}, "properties": {"mag": 4.2}}


@pytest.mark.parametrize(
    "payload",
    [
        _collection([_POINT]),
        _collection([]),
        json.dumps(_POINT).encode(),
        json.dumps({"type": "Feature", "geometry": None, "properties": None}).encode(),
        json.dumps({"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": [0, 0]}]}).encode(),
    ],
)
def test_well_formed_geojson_passes(tmp_path: Path, payload: bytes) -> None:
    assert _check(tmp_path, "geojson_v1", payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        b"{not json",
        json.dumps({"type": "Collection", "features": []}).encode(),
        json.dumps({"type": "FeatureCollection"}).encode(),
        json.dumps({"type": "FeatureCollection", "features": [{"type": "Point", "coordinates": [0, 0]}]}).encode(),
        json.dumps({"type": "Feature", "geometry": {"type": "Point"}, "properties": {}}).encode(),
        json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": 3}).encode(),
        json.dumps([1, 2, 3]).encode(),
    ],
)
def test_broken_geojson_is_named_by_one_code(tmp_path: Path, payload: bytes) -> None:
    assert _check(tmp_path, "geojson_v1", payload) == "WORKSPACE_FORMAT_GEOJSON_INVALID"


@pytest.mark.parametrize("profile", ["epub_v1", "pdf_v1", "geojson_v1"])
def test_the_contract_model_accepts_the_new_profiles(profile: str) -> None:
    rule = WorkspaceArtifactRule.model_validate(
        {
            "path_pattern": "out/*",
            "role": "deliverable",
            "media_type": "application/octet-stream",
            "validation_profile": profile,
        }
    )
    assert rule.validation_profile == profile


def test_core_gives_the_same_verdict_as_the_ruler(tmp_path: Path) -> None:
    rule = WorkspaceArtifactRule.model_validate(
        {"path_pattern": "book.epub", "role": "deliverable", "media_type": "application/epub+zip",
         "validation_profile": "epub_v1"}
    )
    good = tmp_path / "good.epub"
    good.write_bytes(_epub())
    _validate_format(good, rule)
    bad = tmp_path / "bad.epub"
    bad.write_bytes(_epub(mimetype=b"text/plain"))
    with pytest.raises(WorkspaceBundleError) as caught:
        _validate_format(bad, rule)
    assert "WORKSPACE_FORMAT_EPUB_INVALID" in str(caught.value)
