"""退化的录制体是构建器的事,要在生产者跑之前说出来(incident-degenerate-recording-blamed-on-producer-*)。

d4(open-meteo)attempt-7:生产者六轮「unpack_from requires a buffer of at least 8 bytes … actual buffer
size is 1」,五次修复全给生产者——构建器手写的 FlatBuffers 编码器每个录制体只写出 1 字节,
生产者怎么改都解不出。录制体是夹具的一部分,退化(空/1 字节/JSON 不可解析)在物化时就能看见。

不变量:
  I1 assert_recordings_well_formed:任何 < 2 字节的录制体、或 content_type 为 JSON 却解析不了的录制体 →
     WorkspaceBundleError(FIXTURE_RECORDING_DEGENERATE),diagnostics 指名夹具与文件;
  I2 该码 owner CONTRACT、路由 builder;
  I3 正常录制体不受影响;没有 __responses__ 的离线夹具不受影响。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.adoption.intake import draft_selfcheck
from repoproof.adoption.intake.workspace_fixtures import assert_recordings_well_formed
from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import product_jobs


def _fixture(tmp_path: Path, bodies: dict[str, bytes], content_type: str = "application/octet-stream") -> Path:
    root = tmp_path / "fixture"
    responses = root / "__responses__"
    responses.mkdir(parents=True)
    rows = []
    for name, body in bodies.items():
        (responses / name).write_bytes(body)
        rows.append({"method": "GET", "host": "api.example.org", "path": f"/{name}", "query": "", "status": 200,
                     "content_type": content_type, "body": name})
    (responses / "manifest.json").write_text(json.dumps({"schema_version": 1, "responses": rows}), encoding="utf-8")
    return root


def test_a_one_byte_body_is_the_builders_defect(tmp_path: Path) -> None:
    root = _fixture(tmp_path, {"body_000.bin": b"\x00", "body_001.bin": b"\x00" * 64})
    with pytest.raises(WorkspaceBundleError) as caught:
        assert_recordings_well_formed(root, fixture_id="anon-scenario")
    assert caught.value.code == "FIXTURE_RECORDING_DEGENERATE"
    joined = " ".join(caught.value.diagnostics)
    assert "body_000.bin" in joined and "anon-scenario" in joined
    assert product_jobs._workspace_fixture_failure_owner("FIXTURE_RECORDING_DEGENERATE") == "CONTRACT"
    assert draft_selfcheck.repair_target_for("FIXTURE_RECORDING_DEGENERATE", round_index=1) == "builder"


def test_unparseable_json_is_degenerate_too(tmp_path: Path) -> None:
    root = _fixture(tmp_path, {"body_000.json": b"{not json"}, content_type="application/json")
    with pytest.raises(WorkspaceBundleError) as caught:
        assert_recordings_well_formed(root, fixture_id="anon-scenario")
    assert caught.value.code == "FIXTURE_RECORDING_DEGENERATE"


def test_healthy_and_offline_fixtures_pass(tmp_path: Path) -> None:
    assert_recordings_well_formed(_fixture(tmp_path, {"body_000.json": b'{"ok": true}'}, "application/json"),
                                  fixture_id="anon-scenario")
    offline = tmp_path / "offline"
    offline.mkdir()
    (offline / "config.json").write_text("{}", encoding="utf-8")
    assert_recordings_well_formed(offline, fixture_id="anon-offline")
