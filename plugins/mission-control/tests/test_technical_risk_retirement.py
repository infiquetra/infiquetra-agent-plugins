"""T1000-09: retire the live Technical Risk project-field producer (#1000)."""

# ruff: noqa: E402,I001

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PLUGIN_ROOT / "config" / "sdlc-schema.json"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
ALLOWED_RELATIVE = {
    Path("CHANGELOG.md"),
    Path("tests/test_template_sync.py"),
    Path("tests/test_technical_risk_retirement.py"),
}


def _schema_fields_by_key() -> dict[str, dict]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issue_fields = schema["issue_fields"]
    return {field["key"]: field for field in issue_fields["fields"]}


def test_t1000_09_technical_risk_project_field_is_retired() -> None:
    risk_constant = getattr(sdlc_manager, "_PREPARED_FIELD_RISK", None)
    assert risk_constant != "Technical Risk", (
        "live _PREPARED_FIELD_RISK still maps Risk to a Technical Risk project field"
    )

    source = (SCRIPTS_DIR / "sdlc_manager.py").read_text(encoding="utf-8")
    if "Technical Risk" in source:
        assert "E1" in source, (
            "sdlc_manager.py still names Technical Risk without an E1 retirement note"
        )
        assert "decided, not yet created" not in source or "E1" in source

    deny: list[str] = []
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(PLUGIN_ROOT)
        if (
            rel.parts[0] == "tests"
            and rel not in ALLOWED_RELATIVE
            and rel.name
            in {
                "test_issue_prepare_compile_approve.py",
                "test_template_sync.py",
            }
        ):
            continue
        if rel.as_posix().endswith(".md") and rel.parts[0] == "CHANGELOG.md":
            continue
        if rel.suffix not in {".py", ".md"}:
            continue
        if rel in ALLOWED_RELATIVE:
            continue
        if rel.parts[0] != "scripts":
            continue
        text = path.read_text(encoding="utf-8")
        if "Technical Risk" not in text:
            continue
        if "E1" in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "Technical Risk" in line and "E1" not in line:
                deny.append(f"{rel}:{lineno}:{line.strip()}")
    assert deny == [], "live Technical Risk producer remains:\n" + "\n".join(deny)

    fields = _schema_fields_by_key()
    assert fields["risk"]["header"] == "Risk"
    assert fields["risk"]["required"] is True
    matrix = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["issue_fields"]["required_matrix"]
    always_required = matrix["rules"][0]["fields"]
    assert "risk" in always_required
