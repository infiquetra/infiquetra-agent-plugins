"""Plan facts have three independent boundaries: producer/code, rendered facts, saved ticks.

Inline negative controls fail when a helper is bypassed; inventory outside this file
and scheduled canaries independently protect guard removal. No English classifier.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import runpy
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from saga_plan_contract import (
    assert_engine_binding,
    assert_regions,
    assert_row,
    assert_saved_examples,
    save_blocks,
    save_options,
)

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path("plugins/saga/scripts/plan_save_contract.py")


@pytest.fixture
def contract_api() -> ModuleType:
    spec = importlib.util.spec_from_file_location("p5_contract", ROOT / SCRIPT)
    assert spec and spec.loader, f"{SCRIPT}: restore the missing validator"
    api = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = api
    spec.loader.exec_module(api)
    return api


def mutated(api: ModuleType, data: dict[str, Any]) -> Any:
    contract = api.load(text=yaml.safe_dump(data, sort_keys=False))
    assert_engine_binding(api, contract)
    return contract


def cli(api: ModuleType, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / SCRIPT), "--root", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def tree(api: ModuleType, root: Path) -> None:
    # Copy actual code, including fleet shim dependencies, without copying a .saga directory.
    import shutil

    for folder in ("plugins/saga/scripts", "plugins/fleet-core/scripts"):
        shutil.copytree(ROOT / folder, root / folder, ignore=shutil.ignore_patterns("__pycache__"))
    for path in (
        api.CONTRACT,
        api.SKILL,
        api.SPEC,
        api.EFFORT_REFERENCE,
    ):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes((ROOT / path).read_bytes())


def test_plan_save_contract_loads_and_rejects_malformed_entries(contract_api: ModuleType) -> None:
    api = contract_api
    original = api.load().data
    cases: list[tuple[dict[str, Any], str]] = []

    def case(section: str, key: str, value: Any, message: str) -> None:
        data = copy.deepcopy(original)
        data[section][0][key] = value
        cases.append((data, message))

    value: Any
    for value in ([], {}, None, "sometimes"):
        case("writes", "when", value, "when")
    for value in ("", "\x00", "one\ntwo", 3):
        case("identity", "placeholder", value, "placeholder")
    case("writes", "when", {"field": [], "equals": "pr"}, "when")
    case("writes", "when", {"field": "lifecycle_phase", "equals": "plan"}, "another declared")
    case("writes", "when", {"field": "destination", "equals": "staging"}, "destination")
    case("writes", "value", "done", "lifecycle_phase")
    case("writes", "placeholder", "<phase>", "keys")
    case("templates", "fixed", {"no_such_p5_field": "x"}, "unknown field")
    case("templates", "fixed", {"destination": "staging"}, "destination")
    case("templates", "fixed", {"lifecycle_phase": "work"}, "contract constant")
    case("templates", "fixed", [], "fixed")
    case("templates", "omit", ["deploy_autonomy"], "keys")
    case("writes", "name", "not an identifier", "identifier")
    case("writes", "name", "help", "save option")
    for section in ("writes", "identity", "templates"):
        for value in (
            [],
            [None],
            [copy.deepcopy(original[section][0]), copy.deepcopy(original[section][0])],
        ):
            data = copy.deepcopy(original)
            data[section] = value
            cases.append((data, section))
    for field, value in [
        ("seam", "missing"),
        ("parameters", ["x"]),
        ("spawn_kinds", {}),
        ("spawn_kinds", {"agent": []}),
        ("reference", "\x00"),
        ("reference", "../outside"),
        ("reference", "missing.md"),
    ]:
        data = copy.deepcopy(original)
        data["effort_honoring"][field] = value
        cases.append((data, "effort_honoring"))
    for schema in ("plan_save_contract.v99", "bridge_signatures.v1", None):
        data = copy.deepcopy(original)
        data["schema"] = schema
        cases.append((data, "schema.*matching tool revision"))
    for data, diagnostic in cases:
        with pytest.raises(api.ContractError, match="plan-save-contract.yaml:.*" + diagnostic):
            mutated(api, data)
    literal = copy.deepcopy(original)
    path_entry = next(i for i in literal["writes"] if i["name"] == "plan_path")
    path_entry.pop("placeholder")
    path_entry["value"] = "one|two"
    with pytest.raises(api.ContractError, match="plan_path.*value"):
        mutated(api, literal)
    raw = (ROOT / api.CONTRACT).read_text()
    for tag in (
        "!!python/name:builtins.str",
        "!!python/object/apply:builtins.str [unsafe]",
        "!!python/object/new:builtins.str [unsafe]",
    ):
        with pytest.raises(yaml.constructor.ConstructorError):
            api.load(text=tag)
    for suffix, diagnostic in [
        ("\nschema: duplicate\n", "duplicate"),
        ("\nx: &x [*x]\n", "alias"),
        ("\nx: &a [1]\ny: &b [*a, *a]\nz: [*b, *b]\n", "alias"),
    ]:
        with pytest.raises(api.ContractError, match="plan-save-contract.yaml:.*" + diagnostic):
            api.load(text=raw + suffix)


def test_plan_save_contract_binds_to_engine(contract_api: ModuleType, tmp_path: Path) -> None:
    api = contract_api
    original = api.load().data
    tree(api, tmp_path)
    for old, new in [("adr_refs", "p5_impossible_926"), ("orchestration_recommended", "next_step")]:
        data = copy.deepcopy(original)
        next(i for i in data["writes"] if i["name"] == old)["name"] = new
        (tmp_path / api.CONTRACT).write_text(yaml.safe_dump(data, sort_keys=False))
        before = {p: (tmp_path / p).read_bytes() for p in (api.SKILL, api.SPEC)}
        for command in [("validate",), ("render", "--write")]:
            result = cli(api, tmp_path, *command)
            assert result.returncode == 2, result.stdout + result.stderr
            assert "writes" in json.loads(result.stdout)["error"], result.stdout
            assert before == {p: (tmp_path / p).read_bytes() for p in before}
    # A newly introduced condition must exercise both sides even when its field
    # is outside the ordinary destination/backend scenario matrix.
    # ("orchestration_recommended", "inline") was the second pair. Issue 1030 left that enum with
    # one value, so `inline` is now INSIDE the scenario matrix and conditioning on it is valid --
    # the case would assert a rejection that correctly no longer happens. `kind`/`task` is still
    # outside the matrix and still proves the rule.
    for field, value in (("kind", "task"),):
        data = copy.deepcopy(original)
        next(i for i in data["writes"] if i["name"] == "adr_refs")["when"] = {
            "field": field,
            "equals": value,
        }
        (tmp_path / api.CONTRACT).write_text(yaml.safe_dump(data, sort_keys=False))
        before = {p: (tmp_path / p).read_bytes() for p in (api.SKILL, api.SPEC)}
        for command in [("validate",), ("render", "--write")]:
            result = cli(api, tmp_path, *command)
            assert result.returncode == 2, result.stdout + result.stderr
            assert json.loads(result.stdout)["code"] == "verification"
            assert before == {p: (tmp_path / p).read_bytes() for p in before}
    for name in (
        "kind",
        "destination",
        "deploy_autonomy",
        "orchestration_mode",
        "orchestration_recommended",
    ):
        data = copy.deepcopy(original)
        next(i for i in data["identity"] + data["writes"] if i["name"] == name)["placeholder"] = (
            "<bogus>"
        )
        with pytest.raises(api.ContractError, match=name + ".*placeholder.*engine choices"):
            mutated(api, data)
    for kind in original["effort_honoring"]["spawn_kinds"]:
        data = copy.deepcopy(original)
        mechanisms = data["effort_honoring"]["spawn_kinds"]
        mechanisms[kind] = "proxy" if mechanisms[kind] == "native" else "native"
        with pytest.raises(api.ContractError, match="spawn_kinds.*" + kind):
            mutated(api, data)


def save_tick(
    tmp_path: Path, flags: dict[str, str], *, ok: bool = True
) -> tuple[dict[str, Any], str]:
    args = [sys.executable, str(ROOT / "plugins/saga/scripts/saga.py"), "save"]
    for name, value in flags.items():
        args += ["--" + name.replace("_", "-"), value]
    # Ask the real parser/builder where this save will write before executing it.
    # Issue IDs are verbatim and explicit saga IDs can override derivation.
    engine = runpy.run_path(str(ROOT / "plugins/saga/scripts/saga.py"))
    parser = argparse.ArgumentParser()
    engine["_add_save_parser"](parser.add_subparsers())
    incoming, _ = engine["_build_save_saga"](parser.parse_args(args[2:]))
    target = (tmp_path / engine["SAGAS_DIR"] / incoming.saga_id).resolve()
    assert target.is_relative_to(tmp_path.resolve()), (
        "Plan example saga identity escapes its temporary workspace"
    )
    result = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, check=False)
    if not ok:
        assert result.returncode != 0 and "downgrade" in result.stdout + result.stderr, result
        return {}, result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    path = Path(json.loads(result.stdout)["envelope_path"])
    body = (tmp_path / path).read_text()
    return yaml.safe_load(body.split("---", 2)[1]), body


def test_saga_spec_plan_consumer_row_matches_contract(
    contract_api: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = contract_api
    contract = api.load()
    text = (ROOT / api.SPEC).read_text()
    assert_row(api, contract, text)
    real_row = api.render_consumer_row
    with monkeypatch.context() as patch:
        patch.setattr(
            api,
            "render_consumer_row",
            lambda c: real_row(c).replace("`scan` (§2.3)", "`restore` (§99.9)"),
        )
        start, end = api.row_span(text)
        rewritten = text[:start] + api.render_consumer_row(contract) + text[end:]
        with pytest.raises(AssertionError, match="Reads cell differs"):
            assert_row(api, contract, rewritten)
    start, end = api.row_span(text)
    # Derive the mutant token from the actual field sequence; no copied row or fixed index.
    name = contract.data["writes"][0]["name"]
    broken = text[:start] + text[start:end].replace(name, "p5_missing_fact", 1) + text[end:]
    assert broken != text
    with pytest.raises(AssertionError, match="consumer row facts differ"):
        assert_row(api, contract, broken)
    for broken in (text[:start] + text[end:], text + "\n" + text[start:end]):
        with pytest.raises(api.ContractError, match="consumer row"):
            assert_row(api, contract, broken)


def test_plan_docs_generated_regions_match_contract(
    contract_api: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = contract_api
    contract = api.load()
    skill, spec = (ROOT / api.SKILL).read_text(), (ROOT / api.SPEC).read_text()
    assert_regions(api, contract, skill, spec)
    real_note = api.render_effort_note
    with monkeypatch.context() as patch:
        patch.setattr(
            api,
            "render_effort_note",
            lambda c: real_note(c).replace("`<model>/<effort>`", "`<model>`"),
        )
        rewritten = api.rendered_documents(contract, skill, spec)
        # A faulty renderer and its freshly rewritten output agree. The independent
        # factual assertion must still fail; source-to-itself equality is insufficient.
        with pytest.raises(AssertionError, match="factual clauses differ"):
            assert_regions(api, contract, rewritten[api.SKILL], rewritten[api.SPEC])
    broken = skill.replace("--phase-status complete", "--phase-status pending", 1)
    with pytest.raises(AssertionError, match="generated region differs"):
        assert_regions(api, contract, broken, spec)
    for command in (
        "```bash titled\nsaga.py save --id stray\n```",
        "~~~bash\nsaga.py save --id stray\n~~~",
        "    saga.py save --id stray",
        "`saga.py save --id stray`",
    ):
        with pytest.raises(api.ContractError, match="outside generated regions"):
            assert_regions(api, contract, skill + "\n### Later section\n" + command, spec)
    # Renderer must consume new inputs, never derive them from the output document.
    data = copy.deepcopy(contract.data)
    next(i for i in data["writes"] if i["name"] == "plan_path")["placeholder"] = (
        "docs/plans/revised.md"
    )
    revised = mutated(api, data)
    hash_data = copy.deepcopy(contract.data)
    next(i for i in hash_data["writes"] if i["name"] == "decisions")["placeholder"] = "repair #926"
    hashed = api.render_template(mutated(api, hash_data), contract.data["templates"][0]["id"])
    parsed = save_options(save_blocks(hashed)[0])
    assert parsed["decisions"] == ["repair #926"] and "orchestration_recommended" in parsed
    output = api.rendered_documents(revised, skill, spec)[api.SKILL]
    assert "docs/plans/revised.md" in output and output != skill
    with pytest.raises(AssertionError, match="expected exactly one ### 5.3"):
        assert_regions(api, revised, output.replace("### 5.3 ", "### 5.8 "), spec)


def recommender_argv(command: str, root: Path) -> list[str]:
    """Documentation may supply example arguments, never select an executable."""
    args = shlex.split(command)
    expected = ["python3", "plugins/saga/scripts/lifecycle_state.py", "recommend-backend"]
    assert args[:3] == expected, (
        "maintainer runbook: expected the canonical recommend-backend command"
    )
    target = (root / expected[1]).resolve()
    assert target.is_relative_to(root.resolve()), "maintainer runbook: recommender escapes checkout"
    return [sys.executable, str(target), *args[2:]]


# The backend axis had three values; issue #1030 archived team-execution and cc-workflows, so the
# enumeration is one. The destination axis is untouched.
@pytest.mark.parametrize("destination", ["plan-only", "pr", "merge", "nonprod-deploy"])
@pytest.mark.parametrize("backend", ["inline"])
def test_plan_examples_save_the_intended_tick(
    contract_api: ModuleType, tmp_path: Path, destination: str, backend: str
) -> None:
    api = contract_api
    contract = api.load()
    assert_engine_binding(api, contract)
    candidate = api.rendered_documents(
        contract, (ROOT / api.SKILL).read_text(), (ROOT / api.SPEC).read_text()
    )
    assert_regions(api, contract, candidate[api.SKILL], candidate[api.SPEC])
    assert_row(api, contract, candidate[api.SPEC])
    assert_saved_examples(api, contract, tmp_path, destination, backend, probe=save_tick)


def test_an_archived_orchestration_mode_is_refused_at_write_and_read_back_at_rest() -> None:
    """Issue #1030 archived `team-execution`. Both halves of that are load-bearing.

    Refused at the command line, because a new run must not select a backend that is not there.
    Read back at rest, because the enum strings are a durable wire contract and a saga written
    before the archive must not become unreadable -- `_orchestration_rank` returns None for an
    unrecognized value and the provenance guard is lenient, which is exactly that property.
    """
    engine = runpy.run_path(str(ROOT / "plugins/saga/scripts/saga.py"))
    assert "team-execution" not in engine["ORCHESTRATION_MODES"]
    assert engine["_orchestration_rank"]("team-execution") is None
    assert engine["_orchestration_rank"]("inline") == 0
    # The label map deliberately keeps the archived key, so a historical tick renders the label it
    # was written with rather than falling back to the raw enum string.
    assert engine["display_orchestration_mode"]("team-execution") == "team execution"


# ---------------------------------------------------------------------------
# Plan-save contract guards, restored. Issue 1030's sweeps to retire tests of removed modules took
# these four with them, which was wrong: their subject is the plan-save contract and its renderer,
# both of which survive. Nine entries in tools/canary_registry.json name them, and a canary whose
# guard has vanished reports "error", not "caught" -- which is how the loss was found.
# ---------------------------------------------------------------------------


def test_operator_choice_rule_matches_engine(tmp_path: Path) -> None:
    """The derivation rule: the operator choice follows the explicit mode flag, is empty when
    neither is given, and is preserved across a save that names neither.

    This case also exercised the divergence branches -- a choice supplied without a mode, a choice
    differing from the mode, a downgrade rationale authorizing that divergence, a blank rationale
    refused, and a rationale that does not authorize an *upgrade*. Every one of them needs two
    backends to express. Issue 1030 archived both team-execution and cc-workflows, so the
    enumeration is the single value `inline`, a choice can no longer differ from a mode, and those
    branches are unreachable rather than untested. The engine still carries the guard; there is no
    longer an input that reaches it.
    """
    tick, _ = save_tick(tmp_path, {"id": "fresh"})
    assert tick["orchestration_mode"] == "inline" and tick["orchestration_operator_choice"] == ""
    tick, _ = save_tick(tmp_path, {"id": "resume", "orchestration_mode": "inline"})
    assert tick["orchestration_operator_choice"] == "inline"
    tick, _ = save_tick(tmp_path, {"id": "resume"})
    assert tick["orchestration_operator_choice"] == "inline"
    note = (ROOT / "plugins/saga/references/saga-spec.md").read_text()
    assert (
        "`orchestration_operator_choice` (derived from an explicit mode flag unless an explicit "
        "choice is supplied; omitting both preserves the prior choice or starts empty)"
    ) in note


def test_plan_docs_wording_changes_do_not_fail(contract_api: ModuleType, tmp_path: Path) -> None:
    api = contract_api
    contract = api.load()
    skill, spec = (ROOT / api.SKILL).read_text(), (ROOT / api.SPEC).read_text()
    revised = skill.replace("Emit a **runnable** saga", "Produce an **executable** saga")
    revised_spec = spec.replace("Each command below implements", "Every listed command implements")
    revised = revised.replace(
        "### 5.3",
        "Blocked plans: `/work` later records `--blockers`; the saga.py save operation (`saga.py save`) supports other phases.\n\n```bash\nother-tool --status ready # --next-step is unrelated\n```\n\n### 5.3",
        1,
    )
    assert revised != skill and revised_spec != spec
    assert_regions(api, contract, revised, revised_spec)
    assert_row(api, contract, revised_spec)
    heading = next(line[3:] for line in spec.splitlines() if line.startswith("## 11. "))
    anchor = re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
    # The docs model carried the second pointer; issue 1030 retired it with the generated
    # atlas, so the command manual is the one remaining consumer-row pointer.
    for source in ("plugins/saga/docs/commands.md",):
        path = ROOT / source
        match = re.search(
            r"\[/plan consumer row in saga-spec §11\]\(([^)#]+)#([^)]*)\)", path.read_text()
        )
        assert match, f"{source}: missing Plan contract pointer"
        assert (path.parent / match[1]).resolve() == (ROOT / api.SPEC).resolve(), source
        assert match[2] == anchor, f"{source}: broken consumer-row anchor"
    runbook = (ROOT / "plugins/saga/references/plan-save-contract.md").read_text()
    for row in (
        "| 0 | `valid`, `clean`, `rendered` | Input validated, output already current, or output written. |",
        "| 1 | `drift` | `changed` contains relative paths; `diff` contains proposed changes. |",
        "| 2 | `invalid` | Nothing should be retried until the reported failure is corrected. |",
    ):
        assert row in runbook, (
            "maintainer runbook: exit protocol differs from exercised CLI outcomes"
        )
    codes = re.findall(r"^\| `([a-z_]+)` \|", runbook, re.M)
    assert set(codes) == {
        "usage",
        "schema_family",
        "schema_version",
        "invalid_contract",
        "engine",
        "filesystem",
        "syntax",
        "verification",
    }
    assert len(codes) == len(set(codes)), "maintainer runbook: duplicate error code"
    # references/execution-spec.md carried a pointer back at the generated Plan save example.
    # Issue 1030 removed that document with the execution spec it described, so the pointer has no
    # source; the generated region itself is still pinned by assert_regions above.
    for path in re.findall(r"`(plugins/[^`]+\.py)`", runbook):
        assert (ROOT / path).is_file(), f"maintainer runbook: missing {path}"
    commands = [
        block.strip()
        for block in re.findall(r"```bash\n(.*?)```", runbook, re.S)
        if "lifecycle_state.py" in block
    ]
    assert len(commands) == 1, "maintainer runbook: missing runnable recommender example"
    for target in ("/tmp/outside.py", "../outside.py", "plugins/saga/scripts/saga.py", "-c"):
        with pytest.raises(AssertionError, match="canonical recommend-backend"):
            recommender_argv(f"python3 {target} recommend-backend lifecycle_state.py", ROOT)
    linked_root = tmp_path / "linked-checkout"
    linked_script = linked_root / "plugins/saga/scripts/lifecycle_state.py"
    linked_script.parent.mkdir(parents=True)
    linked_script.symlink_to(ROOT / "plugins/saga/scripts/lifecycle_state.py")
    with pytest.raises(AssertionError, match="escapes checkout"):
        recommender_argv(commands[0], linked_root)
    result = subprocess.run(
        recommender_argv(commands[0], ROOT),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0 and json.loads(result.stdout)["recommended"] == "inline"
    # The producer boundary is a section number, never the English heading wording.
    tree(api, tmp_path)
    edited = skill.replace("### 5.3 Write the saga tick", "### 5.3 Save the saga tick")
    assert edited != skill
    (tmp_path / api.SKILL).write_text(edited)
    result = cli(api, tmp_path, "render", "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_plan_renderer_edit_workflow(contract_api: ModuleType, tmp_path: Path) -> None:
    api = contract_api
    tree(api, tmp_path)
    data = api.load().data
    data["templates"].append({"id": "deploy", "fixed": {"destination": "nonprod-deploy"}})
    data["templates"].extend(
        [
            {"id": "merge", "fixed": {"destination": "merge"}},
            {
                "id": "recommendation_example",
                "fixed": {"orchestration_recommended": "inline"},
            },
            {
                "id": "autonomy",
                "fixed": {"destination": "nonprod-deploy", "deploy_autonomy": "auto"},
            },
        ]
    )
    (tmp_path / api.CONTRACT).write_text(yaml.safe_dump(data, sort_keys=False))
    result = cli(api, tmp_path, "render", "--check")
    assert result.returncode == 1 and json.loads(result.stdout)["outcome"] == "drift"
    assert "deploy" in json.loads(result.stdout)["diff"]
    result = cli(api, tmp_path, "render", "--write")
    assert result.returncode == 0 and str(api.SKILL) in json.loads(result.stdout)["changed"]
    result = cli(api, tmp_path, "render", "--check")
    assert result.returncode == 0 and json.loads(result.stdout)["outcome"] == "clean"
    result = cli(api, tmp_path, "render", "--write")
    assert result.returncode == 0 and json.loads(result.stdout)["changed"] == []
    assert_regions(
        api,
        api.load(root=tmp_path),
        (tmp_path / api.SKILL).read_text(),
        (tmp_path / api.SPEC).read_text(),
    )
    for destination in ("pr", "nonprod-deploy"):
        for backend in ("inline",):
            assert_saved_examples(
                api,
                api.load(root=tmp_path),
                tmp_path / f"saved-{destination}-{backend}",
                destination,
                backend,
            )
    # Original checkout is not the target even when running an installed/cached script.
    assert "Example: deploy" not in (ROOT / api.SKILL).read_text()


def test_plan_renderer_refusals_and_rollback(
    contract_api: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = contract_api
    tree(api, tmp_path)
    originals = {p: (tmp_path / p).read_text() for p in (api.SKILL, api.SPEC)}
    for path, name in (
        (api.SKILL, "PLAN SAVE EXAMPLES: default"),
        (api.SKILL, "EFFORT HONORING NOTE"),
    ):
        marker = api.markers(name)[0]
        for text in (
            originals[path].replace(marker, "<!-- MISSING -->"),
            originals[path] + "\n" + marker,
        ):
            (tmp_path / path).write_text(text)
            result = cli(api, tmp_path, "render", "--write")
            assert result.returncode == 2 and name in json.loads(result.stdout)["error"]
            assert (tmp_path / api.SPEC).read_text() == originals[api.SPEC]
        (tmp_path / path).write_text(originals[path])
    raw = (tmp_path / api.CONTRACT).read_text()
    data = yaml.safe_load(raw)
    next(i for i in data["writes"] if i["name"] == "plan_path")["placeholder"] = "revised.md"
    (tmp_path / api.CONTRACT).write_text(yaml.safe_dump(data, sort_keys=False))
    for heading in ("5.3", "5.4"):
        broken = originals[api.SKILL].replace(f"### {heading} ", "### 5.8 ")
        (tmp_path / api.SKILL).write_text(broken)
        for command in (("validate",), ("render", "--write")):
            result = cli(api, tmp_path, *command)
            detail = json.loads(result.stdout)
            assert result.returncode == 2 and heading in detail["error"], result.stdout
            assert "expected exactly one" in detail["error"]
            assert detail["file"] == str(api.SKILL)
            assert (tmp_path / api.SKILL).read_text() == broken
            assert (tmp_path / api.SPEC).read_text() == originals[api.SPEC]
    (tmp_path / api.SKILL).write_text(originals[api.SKILL])
    (tmp_path / api.CONTRACT).write_text(raw)
    for args in [
        (),
        ("render",),
        ("render", "--check", "--write"),
        ("--contract", "foreign.yaml", "validate"),
    ]:
        result = cli(api, tmp_path, *args)
        assert result.returncode == 2 and json.loads(result.stdout)["outcome"] == "invalid"
    # Invalid schema and missing/renamed Python interfaces have a JSON refusal, never a traceback.
    raw = (tmp_path / api.CONTRACT).read_text()
    for schema, code in [
        ("plan_save_contract.v99", "schema_version"),
        ("unrelated.v1", "schema_family"),
    ]:
        (tmp_path / api.CONTRACT).write_text(raw.replace(api.SCHEMA, schema))
        result = cli(api, tmp_path, "validate")
        assert result.returncode == 2 and json.loads(result.stdout)["code"] == code
    (tmp_path / api.CONTRACT).write_text(raw)
    engine = tmp_path / "plugins/saga/scripts/saga.py"
    original_engine = engine.read_text()
    for content in [
        "import p5_module_that_cannot_exist_926",
        original_engine.replace("def _add_save_parser(", "def _removed_save_parser("),
    ]:
        engine.write_text(content)
        result = cli(api, tmp_path, "validate")
        assert result.returncode == 2 and json.loads(result.stdout)["outcome"] == "invalid"
        assert "Traceback" not in result.stderr
        assert json.loads(result.stdout)["file"] == "plugins/saga/scripts/saga.py"
    engine.write_text(original_engine)
    # Force actual second-replacement failure after both files were successfully staged.
    replacement = {p: text + "\nchanged\n" for p, text in originals.items()}
    real_replace = api.os.replace

    def fail_second(src: Path, dst: Path) -> None:
        if dst == tmp_path / api.SPEC:
            raise PermissionError("injected second-document replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(api.os, "replace", fail_second)
    with pytest.raises(api.ContractError, match="all changes rolled back"):
        api.write_documents(tmp_path, originals, replacement, list(originals))
    assert originals == {p: (tmp_path / p).read_text() for p in originals}
    assert not list(tmp_path.rglob(".plan-contract-*"))

    # A staging failure happens before either destination is replaced.
    monkeypatch.setattr(api.os, "replace", real_replace)
    real_temp = api.tempfile.NamedTemporaryFile
    calls = 0

    def fail_stage(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("injected staging failure")
        return real_temp(**kwargs)

    monkeypatch.setattr(api.tempfile, "NamedTemporaryFile", fail_stage)
    with pytest.raises(PermissionError, match="staging failure"):
        api.write_documents(tmp_path, originals, replacement, list(originals))
    assert originals == {p: (tmp_path / p).read_text() for p in originals}
    assert not list(tmp_path.rglob(".plan-contract-*"))
    monkeypatch.setattr(api.tempfile, "NamedTemporaryFile", real_temp)
    # If even rollback is denied, report the retained backup, never claim no changes.
    calls = 0

    def fail_rollback(src: Path, dst: Path) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise PermissionError("injected replacement and rollback failure")
        real_replace(src, dst)

    monkeypatch.setattr(api.os, "replace", fail_rollback)
    with pytest.raises(api.ContractError, match="rollback incomplete") as error:
        api.write_documents(tmp_path, originals, replacement, list(originals))
    backups = list(tmp_path.rglob(".plan-contract-*"))
    assert len(backups) == 1 and str(backups[0]) in str(error.value)
    assert backups[0].read_text() == originals[api.SKILL]
    real_replace(backups[0], tmp_path / api.SKILL)
    assert originals == {p: (tmp_path / p).read_text() for p in originals}
    monkeypatch.setattr(api.os, "replace", real_replace)
    # The callable CLI uses the same result envelope as the subprocess interface.
    assert api.main(["--root", str(tmp_path), "render", "--check"]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "clean"
