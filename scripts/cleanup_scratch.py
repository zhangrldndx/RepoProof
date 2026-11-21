#!/usr/bin/env python3
"""Reclaim scratch space left behind by journeys and test runs.

What it removes (never ledgers, never frozen tasks, never controls/ or runs/):
  * /tmp/rp-*                       — operator scratch (probe venvs, suite logs, ad-hoc replays)
  * $TMPDIR/rp-*  older than --stale-minutes — per-run reference envs, receipts, smoke dirs
  * $TMPDIR/pytest-of-*             — pytest's own temp trees
  * ~/.repoproof/drafts/journey-*   — draft bundles NOT referenced by any attempt under
                                      --planning-dir and older than --keep-days

Dry-run by default; pass --apply to delete.  A running batch is safe: its bundles are
referenced by the planning dir and its temp dirs are younger than --stale-minutes.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def _size_kb(path: Path) -> int:
    try:
        return int(subprocess.check_output(["du", "-sk", str(path)], stderr=subprocess.DEVNULL).split()[0])
    except (subprocess.CalledProcessError, ValueError, IndexError):
        return 0


def referenced_bundles(planning_dirs: list[Path]) -> set[str]:
    names: set[str] = set()
    for root in planning_dirs:
        for stage in glob.glob(str(root / "*" / "*attempt-*" / "stages" / "*.json")):
            try:
                document = json.loads(Path(stage).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            bundle = document.get("draft_bundle") if isinstance(document, dict) else None
            if bundle:
                names.add(os.path.basename(str(bundle)))
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--planning-dir", action="append", default=[], help="planning dir whose attempts pin bundles (repeatable)"
    )
    parser.add_argument("--keep-days", type=float, default=1.0, help="unreferenced bundles younger than this are kept")
    parser.add_argument("--stale-minutes", type=float, default=120.0, help="temp rp-* dirs younger than this are kept")
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    args = parser.parse_args()

    now = time.time()
    victims: list[tuple[str, Path]] = []
    for path in sorted(Path("/tmp").glob("rp-*")):
        victims.append(("tmp", path))
    tmpdir = Path(tempfile.gettempdir())
    for path in sorted(tmpdir.glob("rp-*")):
        if now - path.stat().st_mtime > args.stale_minutes * 60:
            victims.append(("tempdir", path))
    for path in sorted(tmpdir.glob("pytest-of-*")):
        victims.append(("pytest", path))
    planning = [Path(p) for p in args.planning_dir] or sorted(Path("runs").glob("*-qualification-planning"))
    pinned = referenced_bundles(planning)
    drafts = Path.home() / ".repoproof" / "drafts"
    if drafts.is_dir():
        for path in sorted(drafts.iterdir()):
            if not path.is_dir() or path.name in pinned:
                continue
            if now - path.stat().st_mtime > args.keep_days * 86400:
                victims.append(("bundle", path))

    total = 0
    by_kind: dict[str, tuple[int, int]] = {}
    for kind, path in victims:
        kb = _size_kb(path)
        total += kb
        count, size = by_kind.get(kind, (0, 0))
        by_kind[kind] = (count + 1, size + kb)
    for kind, (count, size) in by_kind.items():
        print(f"{kind:8s} {count:5d} entries {size / 1024:8.1f} MB")
    print(f"{'total':8s} {len(victims):5d} entries {total / 1024:8.1f} MB  (pinned bundles: {len(pinned)})")
    if not args.apply:
        print("dry run — pass --apply to delete")
        return 0
    removed = 0
    for _kind, path in victims:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            print(f"skip {path}: {exc}")
    print(f"removed {removed} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
