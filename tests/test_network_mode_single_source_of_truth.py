"""网络模式只有一份字面量(incident-network-mode-literal-duplicated-*)。

prework 1 把 product_profile 里的 DeliveryRequirements.network 三值化,领域模型里同一维度的
副本(FrozenDeliveryRequirements)没有同步:自检、确认、wheelhouse 冻结全部通过,冻结任务时
TaskContract 才以 pydantic 报文判死。同一事实两处写,必然有一处忘。

不变量:
  I1 FrozenDeliveryRequirements 接受 network=open_api(离线/required 不变);
  I2 三值网络模式在 src 里只定义一次(domain.models.NetworkMode),其余处引用它。
"""

from __future__ import annotations

import re
from pathlib import Path

from repoproof.domain import models


def _requirements(network: str) -> dict:
    return {
        "inputs": [
            {"kind": "directory", "location": "local", "representation": "utf8_text", "format_label": "d", "role": "r"}
        ],
        "outputs": [{"kind": "directory", "format_id": "workspace_bundle", "format_label": "w", "role": "r"}],
        "network": network,
        "credentials": "none",
        "lifecycle": "per_invocation",
        "runtime": "local_cpu",
    }


def test_frozen_requirements_accept_every_network_mode() -> None:
    for mode in ("offline", "open_api", "required"):
        assert models.FrozenDeliveryRequirements.model_validate(_requirements(mode)).network == mode


def test_the_network_mode_literal_is_defined_once() -> None:
    assert models.NetworkMode is not None
    src = Path("src/repoproof")
    pattern = re.compile(r'Literal\[\s*"offline",\s*("open_api",\s*)?"required"\s*\]')
    hits = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if path.is_file() and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert hits == ["domain/models.py"], hits
