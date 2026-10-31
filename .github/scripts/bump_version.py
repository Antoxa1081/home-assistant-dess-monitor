"""Compute and write the next integration version for the Release workflow.

Usage: bump_version.py <patch|minor|major> [explicit_version]

Reads ``custom_components/dess_monitor/manifest.json``, computes the new
version (or validates the explicit one), rewrites the manifest in place and
prints the new version on stdout.

Bump rules work on the first three numbers; a fourth pre-release-style part
(``0.4.3.4``) is dropped by any bump. An explicit version may have 3 or 4
numeric parts and must be greater than the current one.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MANIFEST = Path("custom_components/dess_monitor/manifest.json")
_VERSION_RE = re.compile(r"^\d+(\.\d+){2,3}$")


def _parts(version: str) -> tuple[int, ...]:
    if not _VERSION_RE.match(version):
        raise ValueError(f"invalid version {version!r}: expected X.Y.Z or X.Y.Z.N")
    return tuple(int(p) for p in version.split("."))


def next_version(current: str, bump: str, explicit: str | None = None) -> str:
    cur = _parts(current)
    if explicit:
        new = _parts(explicit)
        # Compare padded to 4 parts so 0.4.6 < 0.4.6.1 < 0.4.7.
        if new + (0,) * (4 - len(new)) <= cur + (0,) * (4 - len(cur)):
            raise ValueError(f"version {explicit} is not greater than {current}")
        return explicit
    major, minor, patch = cur[:3]
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "major":
        return f"{major + 1}.0.0"
    raise ValueError(f"unknown bump {bump!r}: expected patch, minor or major")


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    bump = argv[1]
    explicit = argv[2].strip().removeprefix("v") if len(argv) == 3 and argv[2].strip() else None
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        version = next_version(manifest["version"], bump, explicit)
    except ValueError as err:
        print(f"::error::{err}", file=sys.stderr)
        return 1
    manifest["version"] = version
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
