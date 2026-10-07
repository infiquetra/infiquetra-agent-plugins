"""Every saga command-line script must answer ``--help`` with no credentials.

This is the package-local form of ``tests/test_client_entrypoints.py``. That
file only exercises packages that still carry a provenance manifest, and saga
is authored here, so the check lives with the package.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
SCRIPTS = PACKAGE / "scripts"

# Modules that belong to this package or to the bundled Fleet Core copy. A
# missing one of these is a broken entrypoint, not an optional dependency.
INTERNAL = frozenset(
    {
        "bundled_fleet",
        "environment_lease",
        "fleet_commons_shim",
        "intent_envelope",
        "jev_log",
        "jev_sweep",
        "jev_verbs",
        "jev_widen",
        "langfuse_client",
        "merge_guard",
        "merge_turn",
        "plugin_resolution",
        "retry_backoff",
        "run_record",
        "staffing",
        "tier_palette",
        "tier_resolver",
        "typesafe_client",
    }
)

CREDENTIAL_PREFIXES = (
    "TYPESAFE_", "GH_", "GITHUB_", "INFIQUETRA_", "SAGA_LANGFUSE_", "LANGFUSE_",
)


def test_entrypoint_internal_includes_jev_sweep() -> None:
    assert "jev_sweep" in INTERNAL


def test_bundled_langfuse_client_loads() -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        bundled_fleet = importlib.import_module("bundled_fleet")
        client = bundled_fleet.load("langfuse_client")
    finally:
        sys.path.remove(str(SCRIPTS))
    assert Path(client.__file__).resolve().parent == SCRIPTS / "_bundled"
    redaction_source = Path(client.redact.__code__.co_filename).resolve()
    assert redaction_source == SCRIPTS / "_bundled" / "typesafe_client.py"


def _scripts() -> list[Path]:
    found = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name.startswith("_") or path.name == "bundled_fleet.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "ArgumentParser" not in text and "argparse" not in text:
            continue
        found.append(path)
    return found


def _missing_third_party(stderr: str) -> str | None:
    match = re.search(r"ModuleNotFoundError:\s+No module named '([^']+)'", stderr)
    if not match:
        return None
    missing = match.group(1).split(".")[0]
    if missing in INTERNAL:
        return None
    try:
        importlib.import_module(missing)
    except ImportError:
        return missing
    return None


@pytest.mark.parametrize("script", _scripts(), ids=lambda path: path.name)
def test_script_answers_help_without_credentials(script: Path) -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(key.startswith(prefix) for prefix in CREDENTIAL_PREFIXES)
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        cwd=PACKAGE,
    )
    missing = _missing_third_party(completed.stderr)
    if missing:
        pytest.skip(f"{script.name} requires third-party dependency {missing!r}")
    assert completed.returncode == 0, (
        f"{script.name} --help exited {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    combined = (completed.stdout + completed.stderr).lower()
    assert "usage:" in combined or script.name in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr
    assert "Traceback" not in completed.stderr
    for prefix in CREDENTIAL_PREFIXES:
        assert prefix + "API_KEY" not in completed.stdout
        assert prefix + "TOKEN" not in completed.stdout
