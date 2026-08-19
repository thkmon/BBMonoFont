#!/usr/bin/env python3
"""Verify the immutable upstream font inputs without third-party packages."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "SOURCES.sha256"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest().upper()


def main() -> int:
    failures: list[str] = []
    checked = 0
    for raw_line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        expected, relative = line.split(maxsplit=1)
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing: {relative}")
            continue
        actual = digest(path)
        if actual != expected.upper():
            failures.append(f"hash mismatch: {relative}\n  expected {expected}\n  actual   {actual}")
        checked += 1
    if failures:
        print("Source verification failed:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"Verified {checked} immutable source files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
