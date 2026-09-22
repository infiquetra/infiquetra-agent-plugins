"""mission-control executor-profile lint (issue #463, U4 — second palette consumer).

Oracles pinned here:

* happy — a valid profile passes (exit 0); above-sonnet WITH justification passes.
* edge — missing profile block is a distinct named outcome (exit 2, ``no-profile-block``),
  not a crash; sonnet-or-below needs no justification.
* error — unknown model / unknown effort / above-sonnet-without-justification each produce a
  named finding (exit 1).
* provenance — the palette really arrives through the shim: pointing ``FLEET_COMMONS_ROOT`` at
  a fake fleet-core whose palette omits ``opus`` flips opus to unknown-model.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
LINT_PATH = PACKAGE / "scripts" / "executor_profile_lint.py"


def _load_lint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("executor_profile_lint", LINT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LINT = _load_lint()


def _profile_body(
    *, model: str = "sonnet", effort: str = "medium", justification: str | None = None
) -> str:
    lines = [
        "## Context",
        "Some issue prose.",
        "",
        "### Recommended Executor Profile",
        f"- **Model:** {model}",
        f"- **Effort:** {effort}",
        "- **Backend:** inline",
    ]
    if justification is not None:
        lines.append(f"- **Justification (required — profile is above sonnet):** {justification}")
    lines += ["", "### Definition of Done", "- Merged."]
    return "\n".join(lines)


@pytest.fixture()
def fresh_palette_cache(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in ("FLEET_COMMONS_ROOT", "FLEET_COMMONS_DEBUG", "CLAUDE_PLUGIN_ROOT"):
        monkeypatch.delenv(var, raising=False)
    for key in [k for k in sys.modules if k.startswith("_fleet_commons_")]:
        monkeypatch.delitem(sys.modules, key)
    return monkeypatch


def test_valid_profile_passes(fresh_palette_cache: pytest.MonkeyPatch) -> None:
    code, messages = LINT.lint_body(_profile_body(model="sonnet", effort="medium"))
    assert code == 0
    assert messages == ["executor-profile-lint: ok (model=sonnet effort=medium)"]


def test_unknown_model_is_a_named_finding(fresh_palette_cache: pytest.MonkeyPatch) -> None:
    code, messages = LINT.lint_body(_profile_body(model="gpt-4"))
    assert code == 1
    assert any("unknown-model 'gpt-4'" in m for m in messages)


def test_unknown_effort_is_a_named_finding(fresh_palette_cache: pytest.MonkeyPatch) -> None:
    code, messages = LINT.lint_body(_profile_body(effort="med"))
    assert code == 1
    assert any("unknown-effort 'med'" in m for m in messages)


def test_above_sonnet_without_justification_fails(
    fresh_palette_cache: pytest.MonkeyPatch,
) -> None:
    code, messages = LINT.lint_body(_profile_body(model="opus", effort="medium"))
    assert code == 1
    assert any("missing-justification" in m for m in messages)


def test_above_sonnet_with_justification_passes(
    fresh_palette_cache: pytest.MonkeyPatch,
) -> None:
    body = _profile_body(model="opus", effort="medium", justification="architectural decision")
    code, messages = LINT.lint_body(body)
    assert code == 0, messages


def test_fable_also_counts_as_above_sonnet(fresh_palette_cache: pytest.MonkeyPatch) -> None:
    code, messages = LINT.lint_body(_profile_body(model="fable"))
    assert code == 1
    assert any("missing-justification" in m for m in messages)


def test_plain_unbolded_bullets_parse(fresh_palette_cache: pytest.MonkeyPatch) -> None:
    """Real corpus shape (e.g. docs/sdlc-issue-drafts pf-single-vocab-source): no bold markers."""
    body = (
        "### Recommended Executor Profile\n- Model: sonnet\n- Effort: medium\n- Backend: inline\n"
    )
    code, messages = LINT.lint_body(body)
    assert code == 0, messages


def test_backticked_values_parse(fresh_palette_cache: pytest.MonkeyPatch) -> None:
    body = (
        "### Recommended Executor Profile\n"
        "- Model: `opus`\n"
        "- Effort: `medium`\n"
        "- **Justification (required — profile is above sonnet):** architectural.\n"
    )
    code, messages = LINT.lint_body(body)
    assert code == 0, messages


def test_packed_single_line_profile_parses(fresh_palette_cache: pytest.MonkeyPatch) -> None:
    """Real corpus shape (pf-team-engine-worker-slot): several fields on one bullet line."""
    body = (
        "### Recommended Executor Profile\n"
        "- **Model**: sonnet. **Effort**: high. **Backend**: inline.\n"
    )
    code, messages = LINT.lint_body(body)
    assert code == 0, messages
    fields = LINT.parse_profile(["- **Model**: sonnet. **Effort**: high. **Backend**: inline."])
    assert fields["model"] == "sonnet"
    assert fields["effort"] == "high"


def test_prose_colons_inside_justification_do_not_spawn_phantom_fields(
    fresh_palette_cache: pytest.MonkeyPatch,
) -> None:
    """Round-2 regression: 'model:'/'effort:' inside justification prose must not override."""
    body = (
        "### Recommended Executor Profile\n"
        "- Justification: uses model: haiku internally for something. Effort: fake.\n"
        "- Model: opus\n"
        "- Effort: high\n"
    )
    fields = LINT.parse_profile(body.splitlines()[1:])
    assert fields["model"] == "opus"
    assert fields["effort"] == "high"
    code, messages = LINT.lint_body(body)
    assert code == 0, messages  # justification present, opus justified


def test_missing_block_is_distinct_named_outcome(
    fresh_palette_cache: pytest.MonkeyPatch,
) -> None:
    code, messages = LINT.lint_body("## Context\nAn issue with no profile block at all.\n")
    assert code == 2
    assert any("no-profile-block" in m for m in messages)


def test_cli_reads_body_file_and_exits_nonzero(
    tmp_path: Path,
    fresh_palette_cache: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(_profile_body(model="opus"))
    exit_code = LINT.main(["--body-file", str(body_file)])
    assert exit_code == 1
    assert "missing-justification" in capsys.readouterr().out
