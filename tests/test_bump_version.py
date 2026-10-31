"""Tests for .github/scripts/bump_version.py (Release workflow helper)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "bump_version.py"
_spec = importlib.util.spec_from_file_location("bump_version", _SCRIPT)
bump_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_version)


@pytest.mark.parametrize(("current", "bump", "expected"), [
    ("0.4.6", "patch", "0.4.7"),
    ("0.4.6", "minor", "0.5.0"),
    ("0.4.6", "major", "1.0.0"),
    ("0.4.3.4", "patch", "0.4.4"),  # 4th part dropped by any bump
    ("0.4.3.4", "minor", "0.5.0"),
])
def test_bumps(current, bump, expected):
    assert bump_version.next_version(current, bump) == expected


@pytest.mark.parametrize(("explicit", "ok"), [
    ("0.4.7", True),
    ("0.4.6.1", True),
    ("0.5.0", True),
    ("0.4.6", False),    # equal
    ("0.4.5.9", False),  # lower
    ("0.4", False),      # too short
    ("v0.4.7", False),   # prefix is stripped by main(), not here
    ("0.4.7-beta", False),
])
def test_explicit_version(explicit, ok):
    if ok:
        assert bump_version.next_version("0.4.6", "patch", explicit) == explicit
    else:
        with pytest.raises(ValueError):
            bump_version.next_version("0.4.6", "patch", explicit)


def test_unknown_bump():
    with pytest.raises(ValueError):
        bump_version.next_version("0.4.6", "huge")


def test_main_rewrites_only_version(tmp_path, monkeypatch, capsys):
    manifest = {"domain": "dess_monitor", "homekit": {}, "requirements": [], "version": "0.4.6"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(bump_version, "MANIFEST", path)

    assert bump_version.main(["bump_version.py", "minor", "  "]) == 0
    assert capsys.readouterr().out.strip() == "0.5.0"
    assert json.loads(path.read_text(encoding="utf-8")) == {**manifest, "version": "0.5.0"}

    assert bump_version.main(["bump_version.py", "patch", "v0.6.1"]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == "0.6.1"


def test_main_rejects_lower_version_and_keeps_file(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"version": "0.4.6"}, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(bump_version, "MANIFEST", path)
    assert bump_version.main(["bump_version.py", "patch", "0.4.0"]) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == "0.4.6"


def test_real_manifest_roundtrip_is_byte_identical():
    # The workflow rewrites the manifest with json.dumps(indent=2); make sure
    # that leaves every other byte untouched.
    real = Path(__file__).resolve().parents[1] / "custom_components" / "dess_monitor" / "manifest.json"
    raw = real.read_text(encoding="utf-8")
    assert json.dumps(json.loads(raw), indent=2, ensure_ascii=False) + "\n" == raw
