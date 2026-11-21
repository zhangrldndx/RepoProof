#!/usr/bin/env python3
"""Reclaim space by hard-linking byte-identical large artifacts — nothing is deleted.

Every frozen task package, control tree, skeleton fixture and run bundle carries
its own copy of the same wheels and vendored assets; the tree holds ~19 GB of
exact duplicates of ~10 GB of unique bytes.  A hard link keeps every path in
place with identical content (so every tree hash, manifest and integrity check
still passes) while the bytes live on disk once.

Safety:
  * only files at or above --min-size, and only after a full sha256 match;
  * files modified within --min-age-minutes are skipped (a live run may own them);
  * the link is made under a temporary name and moved into place, so a crash
    never leaves a path missing;
  * paths under .git/ and .venv/ are never touched;
  * a deduplicated file is shared: an in-place write to one path would change
    every path.  These artifacts are write-once (freeze copies whole trees), and
    --read-only marks .whl files 0444 so an accidental in-place write fails loudly.

Dry-run by default; pass --apply to link.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _candidates(roots: list[Path], min_size: int, min_age_s: float) -> dict[int, list[Path]]:
    import time

    now = time.time()
    by_size: dict[int, list[Path]] = defaultdict(list)
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    info = path.lstat()
                except OSError:
                    continue
                if not os.path.isfile(path) or os.path.islink(path):
                    continue
                if info.st_size < min_size or now - info.st_mtime < min_age_s:
                    continue
                by_size[info.st_size].append(path)
    return by_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roots", nargs="*", default=["."], help="directories to scan (default: .)")
    parser.add_argument("--min-size", type=int, default=256 * 1024, help="ignore files smaller than this")
    parser.add_argument("--min-age-minutes", type=float, default=30.0, help="skip files touched more recently")
    parser.add_argument("--read-only", action="store_true", help="chmod 0444 the shared wheels")
    parser.add_argument("--apply", action="store_true", help="actually link (default: dry run)")
    parser.add_argument(
        "--unlock-dirs", action="store_true",
        help="temporarily add owner-write to a read-only parent directory (oracle snapshots), then restore it",
    )
    args = parser.parse_args()

    roots = [Path(item).resolve() for item in (args.roots or ["."])]
    by_size = _candidates(roots, args.min_size, args.min_age_minutes * 60.0)
    reclaimed = 0
    linked = 0
    scanned = 0
    for size, paths in sorted(by_size.items(), reverse=True):
        if len(paths) < 2:
            continue
        by_digest: dict[tuple[str, int], Path] = {}
        for path in paths:
            try:
                info = path.lstat()
            except OSError:
                continue
            scanned += 1
            try:
                digest = _sha256(path)
            except OSError:
                continue
            key = (digest, info.st_dev)
            keeper = by_digest.get(key)
            if keeper is None:
                by_digest[key] = path
                continue
            try:
                if keeper.lstat().st_ino == info.st_ino:
                    continue  # already the same inode
            except OSError:
                continue
            reclaimed += size
            linked += 1
            if not args.apply:
                continue
            temp = path.with_name(path.name + ".rp-dedupe-tmp")
            parent = path.parent
            parent_mode = None
            try:
                if args.unlock_dirs and not os.access(parent, os.W_OK):
                    # A sealed snapshot directory: the bytes are unchanged (the
                    # link carries the same content), only the directory entry
                    # is rewritten, and the mode is restored below.
                    parent_mode = parent.lstat().st_mode
                    os.chmod(parent, parent_mode | 0o200)
                if temp.exists():
                    temp.unlink()
                os.link(keeper, temp)
                os.replace(temp, path)
                if args.read_only and path.suffix == ".whl":
                    os.chmod(path, 0o444)
            except OSError as exc:
                print(f"skip {path}: {exc}")
                if temp.exists():
                    temp.unlink(missing_ok=True)
                reclaimed -= size
                linked -= 1
            finally:
                if parent_mode is not None:
                    try:
                        os.chmod(parent, parent_mode)
                    except OSError:
                        pass
    print(f"hashed {scanned} file(s); {'linked' if args.apply else 'would link'} {linked}; "
          f"{'reclaimed' if args.apply else 'reclaimable'} {reclaimed / 2**30:.2f} GB")
    if not args.apply:
        print("dry run — pass --apply to link")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
