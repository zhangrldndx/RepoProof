"""许可证要从它实际所在的地方读出来(incident-license-not-identified-*)。

geojson:LICENSE.rst(BSD 措辞)不在候选文件名里,setup.py classifier 写着 BSD License;
fpdf2:LICENSE 是 LGPL(关键词表没有),pyproject 写着 license = "LGPL-3.0-only"。两例的 autopilot 旅程
都在 confirm_intent 以 SOURCE_REPO_LICENSE_MISSING 终止——一个没人能代填的「人工确认」。

不变量:
  I1 detect_license 认 LICENSE.* / LICENCE.* / COPYING.*(任意后缀);
  I2 关键词表认 LGPL(按版本行给 LGPL-3.0 / LGPL-2.1)、ISC、PSF、BSD;
  I3 文件类型未识别或没有文件时,回落 pyproject [project].license(字符串或 {text})与
     classifiers「License :: OSI Approved :: …」,setup.py 的 classifier 字面量同理;
  I4 都没有 → 空(仍需人工确认)。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.analysis.repository_analyzer import detect_license


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_license_rst_with_bsd_wording(tmp_path: Path) -> None:
    text = "Copyright (c) anon\n\nRedistribution and use in source and binary forms, with or without modification"
    root = _repo(tmp_path, {"LICENSE.rst": text})
    assert detect_license(root) == ("BSD", "LICENSE.rst")


def test_lgpl_text_is_recognised_with_its_version(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"LICENSE": "GNU LESSER GENERAL PUBLIC LICENSE\n   Version 3, 29 June 2007\n"})
    assert detect_license(root) == ("LGPL-3.0", "LICENSE")
    lgpl21 = "GNU LESSER GENERAL PUBLIC LICENSE\n   Version 2.1, February 1999\n"
    root2 = _repo(tmp_path / "b", {"LICENSE": lgpl21})
    assert detect_license(root2) == ("LGPL-2.1", "LICENSE")


def test_pyproject_and_classifiers_are_the_fallback(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"pyproject.toml": '[project]\nname = "anon"\nlicense = "LGPL-3.0-only"\n'})
    assert detect_license(root) == ("LGPL-3.0-only", "pyproject.toml [project].license")
    setup = 'setup(name="anon", classifiers=["License :: OSI Approved :: BSD License"])\n'
    root2 = _repo(tmp_path / "b", {"setup.py": setup})
    assert detect_license(root2) == ("BSD License", "setup.py classifier")
    pyproject = '[project]\nname = "anon"\nclassifiers = ["License :: OSI Approved :: MIT License"]\n'
    root3 = _repo(tmp_path / "c", {"LICENSE": "Some bespoke terms nobody recognises\n", "pyproject.toml": pyproject})
    assert detect_license(root3) == ("MIT License", "pyproject.toml classifier")


def test_nothing_known_stays_empty(tmp_path: Path) -> None:
    assert detect_license(_repo(tmp_path, {"README.md": "hi"})) == ("", "")
