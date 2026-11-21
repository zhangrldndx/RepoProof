"""判别探针报「哪一行没被拒」时要给出那一行的原文(incident-discrimination-gap-names-unseen-lines-*)。

d9(rich):四轮「card.svg — 变异 8 次无一被拒;ACCEPTED: edit-line-71, …」,判官改写四次原话不变——
诊断只有行号,而判官修复看到的产物摘录有界,第 71 行早已截掉;判官不知道那行是什么,就不知道该断言什么。

不变量:
  I1 mutation_excerpts(payload, kinds):edit-line-N → 第 N 行原文(有界,实际侧);truncate-last-line → 最后一个非空行原文;
  I2 探针的每条变异记录带 excerpt;
  I3 _discrimination_gap_diagnostics 把 ACCEPTED 的变异写成 kind ("原文摘录")。
"""

from __future__ import annotations

from repoproof.ui.services import product_jobs
from repoproof.verification.workspace_semantic import (
    WorkspaceVerifierDiscriminationV1,
    WorkspaceVerifierFileProbeV1,
    WorkspaceVerifierMutationV1,
    content_mutations,
    mutation_excerpts,
)

_PAYLOAD = (
    b"<svg>\n<text>Package</text>\n<text>rich 13.0.0 -> 15.0.0</text>\n"
    b"<text>click 8.0.0 -> 8.1.7</text>\n</svg>\n"
)


def test_excerpts_quote_the_original_line() -> None:
    kinds = [kind for kind, _payload in content_mutations(_PAYLOAD, limit=3)]
    excerpts = mutation_excerpts(_PAYLOAD, kinds)
    assert set(excerpts) == set(kinds)
    for kind, excerpt in excerpts.items():
        if kind.startswith("edit-line-"):
            line = int(kind.rsplit("-", 1)[1])
            assert excerpt == _PAYLOAD.decode().splitlines()[line - 1].strip()[:120]
    assert excerpts["truncate-last-line"] == "</svg>"


def test_the_gap_diagnostics_carry_the_excerpt() -> None:
    probe = WorkspaceVerifierDiscriminationV1(
        probed_files=1, ok=False, gaps=("card.svg",),
        files=(WorkspaceVerifierFileProbeV1(path="card.svg", discriminated=False, mutations=(
            WorkspaceVerifierMutationV1(
                kind="edit-line-3", result="ACCEPTED", excerpt="<text>rich 13.0.0 -> 15.0.0</text>"
            ),
            WorkspaceVerifierMutationV1(kind="truncate-last-line", result="ACCEPTED", excerpt="</svg>"),
        )),),
    )
    rows = product_jobs._discrimination_gap_diagnostics(probe)
    assert rows and "edit-line-3 (\"<text>rich 13.0.0 -> 15.0.0</text>\")" in rows[0]
    assert "truncate-last-line (\"</svg>\")" in rows[0]
    bare = WorkspaceVerifierMutationV1(kind="edit-line-9", result="ACCEPTED")
    assert bare.excerpt == ""
