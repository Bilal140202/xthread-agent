#!/usr/bin/env python3
"""sync_package.py — regenerate xthread_agent/__init__.py from the source of truth.

The repo's canonical implementation is the single file `xthread-agent.py`
(hyphenated; curl-and-run deployment story, see PROJECT_CONTEXT.md §5).
PyPI distribution needs an importable module name, so the wheel carries a
byte-identical copy as `xthread_agent/__init__.py`.

Divergence is impossible by construction:
  * scripts/sync_package.py regenerates the copy (this script)
  * tests/test_package_sync.py FAILS the suite if the copy ever drifts

Usage:  python3 scripts/sync_package.py [--check]
        --check  verify only (exit 1 on drift, no write) — used by CI
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "xthread-agent.py"
DST = ROOT / "xthread_agent" / "__init__.py"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    src_bytes = SRC.read_bytes()
    if "--check" in sys.argv[1:]:
        if not DST.exists():
            print(f"DRIFT: {DST.relative_to(ROOT)} is missing — run scripts/sync_package.py")
            return 1
        if DST.read_bytes() != src_bytes:
            print("DRIFT: xthread_agent/__init__.py differs from xthread-agent.py — "
                  "run scripts/sync_package.py")
            return 1
        print(f"in sync  sha256={sha256(src_bytes)[:16]}…  ({len(src_bytes)} bytes)")
        return 0
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_bytes(src_bytes)
    print(f"synced xthread-agent.py -> xthread_agent/__init__.py  "
          f"sha256={sha256(src_bytes)[:16]}…  ({len(src_bytes)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
