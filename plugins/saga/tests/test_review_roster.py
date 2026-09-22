"""The roster is resolved by invoking the lifecycle repository's generator (issue 1001).

Nothing here reaches the network, touches a live herdr session, or writes to the
primary checkout's run-record store: every test passes a temporary store root and
either a temporary lifecycle checkout or a generator stub it wrote itself.

The one test that uses the real lifecycle checkout skips when it is absent — an
absent sibling repository is a fact about the machine, and a test that failed on it
would be reporting the machine rather than the code.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess  # nosec B404 — fixed argv in a test helper
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"
MODULE_PATH = SCRIPTS / "review_roster.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def roster_module() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    return _load("review_roster_under_test", MODULE_PATH)


@pytest.fixture(autouse=True)
def _clear_sdlc_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits a real checkout from the shell that started pytest."""
    monkeypatch.delenv("INFIQUETRA_SDLC_PATH", raising=False)
    monkeypatch.delenv("INFIQUETRA_SDLC_ROOT", raising=False)


# ---------------------------------------------------------------------------
# A stub lifecycle checkout: a generator that echoes what it was given
# ---------------------------------------------------------------------------

STUB_GENERATOR = """\
import argparse
import hashlib
import json

parser = argparse.ArgumentParser()
parser.add_argument("--declaration", required=True)
args = parser.parse_args()

declaration = json.loads(open(args.declaration, encoding="utf-8").read())
body = {
    "resolved_at": declaration.get("resolved_at"),
    "run": declaration.get("run", {}),
    "declaration": {"lenses": declaration.get("lenses", {})},
    "lenses": [
        {
            "id": lens_id,
            "always_on": True,
            "scorable": True,
            "threshold": {
                "strictness": "standard",
                "derived_overall_minimum": 9.0,
                "applicable_dimension_minimum": 7,
            },
        }
        for lens_id in (
            "architecture-maintainability",
            "correctness",
            "security",
            "testing",
        )
    ]
    + [
        {"id": lens_id, "always_on": False, "scorable": False, "threshold": {}}
        for lens_id, entry in sorted(declaration.get("lenses", {}).items())
        if entry.get("applies")
    ],
}
canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
roster = {
    "schema": "review_roster.v1",
    "hash": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    **body,
}
deselected = [
    lens_id
    for lens_id, entry in declaration.get("lenses", {}).items()
    if not entry.get("applies") and not str(entry.get("reason", "")).strip()
]
status = "refused" if deselected else "ok"
print(
    json.dumps(
        {
            "roster": roster,
            "validation": {
                "schema": "review_roster_validation.v1",
                "roster_hash": roster["hash"],
                "status": status,
                "checks": [
                    {
                        "name": "applicability",
                        "result": "fail" if deselected else "pass",
                        "detail": "; ".join(deselected) or "every conditional lens is accounted for",
                    }
                ],
            },
        },
        indent=2,
    )
)
"""


def _stub_checkout(tmp_path: Path, *, with_generator: bool = True) -> Path:
    checkout = tmp_path / "sdlc"
    (checkout / "tools" / "docs").mkdir(parents=True)
    if with_generator:
        (checkout / "tools" / "docs" / "gen_review_roster.py").write_text(
            STUB_GENERATOR, encoding="utf-8"
        )
    return checkout


def _declaration(**overrides: Any) -> dict[str, Any]:
    declaration: dict[str, Any] = {
        "schema": "applicability_declaration.v1",
        "resolved_at": "2026-09-19T00:00:00Z",
        "run": {
            "repository": "infiquetra/infiquetra-claude-plugins",
            "issue": 1001,
            "revision": "0" * 40,
        },
        "work_unit": "issue-1001",
        "declared_by": "planner",
        "stack": ["python"],
        "lenses": {
            "adversarial": {"applies": True},
            "privacy": {"applies": False, "reason": "no personal data is touched"},
        },
        "executors": {},
        "concurrency_allocation": {},
    }
    declaration.update(overrides)
    return declaration


# ---------------------------------------------------------------------------
# The declaration built from the run record
# ---------------------------------------------------------------------------


def _record(roster_module: ModuleType, tmp_path: Path) -> Any:
    run_record = _load("run_record_for_roster", SCRIPTS / "run_record.py")
    record = run_record.RunRecord(
        issue=1001,
        repo="infiquetra/infiquetra-claude-plugins",
        run_configuration=run_record.empty_run_configuration(),
        approval_scope=run_record.empty_approval_scope(),
        admission=run_record.empty_admission(),
    )
    record.run_configuration["applicable_lenses"] = {
        "value": {
            "always_on": ["architecture-maintainability", "correctness", "security", "testing"],
            "conditional_applies": {"adversarial": "the change is a gate"},
            "conditional_does_not_apply": {"privacy": "no personal data is touched"},
        },
        "chosen_by": "planner",
        "source": "operator",
    }
    return record


def test_declaration_is_built_from_the_run_record(
    roster_module: ModuleType, tmp_path: Path
) -> None:
    """The lens set comes from admission's answer; the review never invents one."""
    record = _record(roster_module, tmp_path)
    declaration = roster_module.build_declaration(
        record, revision="a" * 40, resolved_at="2026-09-19T00:00:00Z"
    )

    assert declaration["schema"] == "applicability_declaration.v1"
    assert declaration["run"]["issue"] == 1001
    assert declaration["run"]["revision"] == "a" * 40
    assert declaration["lenses"]["adversarial"] == {"applies": True}
    assert declaration["lenses"]["privacy"]["applies"] is False
    assert declaration["lenses"]["privacy"]["reason"] == "no personal data is touched"
    # Always-on lenses are never listed: the catalogue selects them and no
    # declaration can deselect one.
    assert "correctness" not in declaration["lenses"]


def test_declaration_never_reads_the_clock(roster_module: ModuleType, tmp_path: Path) -> None:
    """`resolved_at` is supplied, because the generator hashes it.

    A roster that changed with the time of day could not be reproduced from its
    inputs, and reproducing it is the whole point of the hash.
    """
    record = _record(roster_module, tmp_path)
    first = roster_module.build_declaration(
        record, revision="a" * 40, resolved_at="2026-01-01T00:00:00Z"
    )
    second = roster_module.build_declaration(
        record, revision="a" * 40, resolved_at="2026-01-01T00:00:00Z"
    )
    assert first == second
    assert first["resolved_at"] == "2026-01-01T00:00:00Z"


def test_a_record_with_no_lens_declaration_is_refused(
    roster_module: ModuleType, tmp_path: Path
) -> None:
    run_record = _load("run_record_for_roster", SCRIPTS / "run_record.py")
    record = run_record.RunRecord(
        issue=1001,
        repo="infiquetra/infiquetra-claude-plugins",
        run_configuration=run_record.empty_run_configuration(),
        approval_scope=run_record.empty_approval_scope(),
        admission=run_record.empty_admission(),
    )

    with pytest.raises(roster_module.RosterError, match="no applicable_lenses"):
        roster_module.build_declaration(
            record, revision="a" * 40, resolved_at="2026-09-19T00:00:00Z"
        )


# ---------------------------------------------------------------------------
# Finding the lifecycle checkout
# ---------------------------------------------------------------------------


def test_absent_checkout_is_a_named_refusal_not_a_fallback_roster(
    roster_module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No checkout refuses by name. There is no fallback policy, by design."""
    monkeypatch.setattr(roster_module, "DEFAULT_SDLC_PATH", tmp_path / "nowhere")
    monkeypatch.setattr(roster_module, "_staffing_sdlc_root", lambda _explicit: None)

    with pytest.raises(roster_module.RosterError) as refusal:
        roster_module.resolve_checkout(None)

    message = str(refusal.value)
    assert "INFIQUETRA_SDLC_PATH" in message
    assert "INFIQUETRA_SDLC_ROOT" in message
    assert "no fallback roster" in message.lower()


def test_a_configured_path_that_is_not_a_directory_refuses_by_name(
    roster_module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INFIQUETRA_SDLC_PATH", str(tmp_path / "missing"))

    with pytest.raises(roster_module.RosterError, match="INFIQUETRA_SDLC_PATH"):
        roster_module.resolve_checkout(None)


def test_the_role_prompts_variable_is_read_and_named(
    roster_module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`INFIQUETRA_SDLC_ROOT` resolves, and the resolution says which name it used.

    Sixteen role prompts under `plugins/agent-launcher/roles/` name `_ROOT` while the
    staffing component and mission-control read `_PATH`. Honouring both keeps a review
    working while the two are reconciled; naming which one was read keeps the
    divergence visible instead of silent.
    """
    checkout = _stub_checkout(tmp_path)
    monkeypatch.setenv("INFIQUETRA_SDLC_ROOT", str(checkout))

    resolution = roster_module.resolve_checkout(None)

    assert resolution.path == checkout
    assert resolution.source == "INFIQUETRA_SDLC_ROOT"
    assert "INFIQUETRA_SDLC_PATH is unset" in (resolution.other_env_var_set or "")


def test_the_code_variable_wins_and_the_other_is_recorded(
    roster_module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With both set to different directories, `_PATH` wins and `_ROOT` is recorded."""
    chosen = _stub_checkout(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("INFIQUETRA_SDLC_PATH", str(chosen))
    monkeypatch.setenv("INFIQUETRA_SDLC_ROOT", str(other))

    resolution = roster_module.resolve_checkout(None)

    assert resolution.path == chosen
    assert resolution.source == "INFIQUETRA_SDLC_PATH"
    assert str(other) in (resolution.other_env_var_set or "")


def test_a_checkout_without_the_generator_refuses_by_name(
    roster_module: ModuleType, tmp_path: Path
) -> None:
    """A checkout with no generator refuses; this plugin never reimplements it."""
    checkout = _stub_checkout(tmp_path, with_generator=False)
    resolution = roster_module.resolve_checkout(checkout)

    with pytest.raises(roster_module.RosterError) as refusal:
        roster_module.generator_path(resolution)

    assert "gen_review_roster.py" in str(refusal.value)
    assert "never reimplements" in str(refusal.value)


def test_the_checkout_revision_and_clean_state_are_recorded(
    roster_module: ModuleType, tmp_path: Path
) -> None:
    """The generator reads a working tree, so which one it read is recorded.

    Two runs a day apart can resolve different policy from the same instruction.
    Recording the revision makes that visible rather than leaving it assumed.
    """
    checkout = _stub_checkout(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)  # nosec B603 B607
    subprocess.run(["git", "add", "-A"], cwd=checkout, check=True)  # nosec B603 B607
    subprocess.run(  # nosec B603 B607
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "stub"],
        cwd=checkout,
        check=True,
    )

    resolution = roster_module.resolve_checkout(checkout)

    assert resolution.head != "UNKNOWN"
    assert len(resolution.head) == 40
    assert resolution.policy_dirs_clean is True


# ---------------------------------------------------------------------------
# Invoking the generator
# ---------------------------------------------------------------------------


def test_the_roster_hash_is_the_generators_own(roster_module: ModuleType, tmp_path: Path) -> None:
    """The hash this module reports equals the one the generator printed, byte for byte.

    The generator is invoked directly as the oracle: if this module ever computed a
    hash of its own, the two would diverge here.
    """
    checkout = _stub_checkout(tmp_path)
    resolution = roster_module.resolve_checkout(checkout)
    declaration = _declaration()

    resolved = roster_module.resolve_roster(declaration, checkout=resolution)

    declaration_file = tmp_path / "declaration.json"
    declaration_file.write_text(json.dumps(declaration, indent=2), encoding="utf-8")
    oracle = subprocess.run(  # nosec B603
        [
            sys.executable,
            str(checkout / "tools" / "docs" / "gen_review_roster.py"),
            "--declaration",
            str(declaration_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = json.loads(oracle.stdout)["roster"]["hash"]

    assert resolved.roster_hash == expected
    assert resolved.roster["schema"] == "review_roster.v1"


def test_the_four_always_on_lenses_are_always_selected(
    roster_module: ModuleType, tmp_path: Path
) -> None:
    """No declaration can shrink the always-on set."""
    checkout = _stub_checkout(tmp_path)
    resolution = roster_module.resolve_checkout(checkout)

    resolved = roster_module.resolve_roster(_declaration(), checkout=resolution)
    selected = {row["id"] for row in roster_module.selected_lenses(resolved.roster)}

    assert {
        "architecture-maintainability",
        "correctness",
        "security",
        "testing",
    } <= selected


def test_a_conditional_lens_left_out_with_no_reason_is_refused(
    roster_module: ModuleType, tmp_path: Path
) -> None:
    """An empty section never satisfies the applicability check."""
    checkout = _stub_checkout(tmp_path)
    resolution = roster_module.resolve_checkout(checkout)
    declaration = _declaration(lenses={"privacy": {"applies": False}})

    resolved = roster_module.resolve_roster(declaration, checkout=resolution)

    assert resolved.refused is True
    assert resolved.validation["status"] == "refused"


def test_a_generator_emitting_an_unknown_schema_is_refused(
    roster_module: ModuleType, tmp_path: Path
) -> None:
    """The schema identifier is the contract; an unknown one refuses rather than guesses."""
    checkout = _stub_checkout(tmp_path, with_generator=False)
    (checkout / "tools" / "docs" / "gen_review_roster.py").write_text(
        textwrap.dedent(
            """\
            import json
            print(json.dumps({
                "roster": {"schema": "review_roster.v9", "hash": "sha256:x"},
                "validation": {"status": "ok", "checks": []},
            }))
            """
        ),
        encoding="utf-8",
    )
    resolution = roster_module.resolve_checkout(checkout)

    with pytest.raises(roster_module.RosterError, match="review_roster.v1"):
        roster_module.resolve_roster(_declaration(), checkout=resolution)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_command_line_exits_two_on_a_named_refusal(
    roster_module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setenv("INFIQUETRA_SDLC_PATH", str(tmp_path / "missing"))
    declaration_file = tmp_path / "decl.json"
    declaration_file.write_text(json.dumps(_declaration()), encoding="utf-8")

    code = roster_module.main(["--declaration", str(declaration_file)])

    assert code == roster_module.EXIT_REFUSED
    assert "INFIQUETRA_SDLC_PATH" in capsys.readouterr().err


def test_command_line_exits_one_when_the_generator_refuses(
    roster_module: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    """A refused validation report is a run-setup fact the caller must see."""
    checkout = _stub_checkout(tmp_path)
    declaration_file = tmp_path / "decl.json"
    declaration_file.write_text(
        json.dumps(_declaration(lenses={"privacy": {"applies": False}})), encoding="utf-8"
    )

    code = roster_module.main(
        ["--declaration", str(declaration_file), "--sdlc-path", str(checkout)]
    )

    assert code == roster_module.EXIT_REFUSED_BY_GENERATOR
    printed = json.loads(capsys.readouterr().out)
    assert printed["validation"]["status"] == "refused"


def test_command_line_exits_zero_on_a_clean_resolution(
    roster_module: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    checkout = _stub_checkout(tmp_path)
    declaration_file = tmp_path / "decl.json"
    declaration_file.write_text(json.dumps(_declaration()), encoding="utf-8")

    code = roster_module.main(
        ["--declaration", str(declaration_file), "--sdlc-path", str(checkout)]
    )

    assert code == roster_module.EXIT_OK
    printed = json.loads(capsys.readouterr().out)
    assert printed["roster"]["schema"] == "review_roster.v1"
    assert printed["checkout"]["source"] == "explicit path"


# ---------------------------------------------------------------------------
# Against the real lifecycle repository, when it is on this machine
# ---------------------------------------------------------------------------


def _real_checkout() -> Path | None:
    configured = os.environ.get("INFIQUETRA_SDLC_PATH") or os.environ.get("INFIQUETRA_SDLC_ROOT")
    candidate = (
        Path(configured).expanduser()
        if configured
        else Path.home() / "workspace" / "infiquetra" / "infiquetra-sdlc"
    )
    generator = candidate / "tools" / "docs" / "gen_review_roster.py"
    return candidate if generator.is_file() else None


def test_the_real_generator_needs_no_vendoring(roster_module: ModuleType, tmp_path: Path) -> None:
    """Issue 1001's stop condition, checked rather than assumed.

    The card says to stop if the lifecycle generator cannot be invoked without
    vendoring it. It can: the generator imports only the standard library and
    resolves its own inputs from its own location, so a subprocess call is enough.
    Skipped when the sibling repository is not on this machine.
    """
    checkout = _real_checkout()
    if checkout is None:
        pytest.skip("the lifecycle repository is not checked out on this machine")

    resolution = roster_module.resolve_checkout(checkout)
    resolved = roster_module.resolve_roster(_declaration(), checkout=resolution)

    assert resolved.roster["schema"] == "review_roster.v1"
    assert resolved.roster_hash.startswith("sha256:")
    # Today the validation report refuses on verification_presence, because the
    # lifecycle repository's executor-verification ledger is empty on purpose. That
    # is the honest state, not a failure of this code.
    names = {check["name"] for check in resolved.validation["checks"]}
    assert "verification_presence" in names
