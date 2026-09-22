"""Exercise documentation sinks and refusal envelopes across the real CLI boundary."""

from __future__ import annotations

import copy
import json
import os
import shlex
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from saga_plan_contract import SaveProbe, save_blocks
from test_saga_spec_consumer_row import (
    ROOT,
    SCRIPT,
    cli,
    contract_api,
    mutated,
    save_tick,
    tree,
)

__all__ = ["contract_api"]


def test_contract_values_are_shell_data(contract_api: ModuleType, tmp_path: Path) -> None:
    api = contract_api
    original = api.load().data
    marker = tmp_path / "must-not-execute"
    for value in (
        "docs/plans/plan.md #topic",
        "KTD1: repair #926. --issue-ref is text.",
        f"$(touch {marker})",
        f"`touch {marker}`",
        "a 'single' and \"double\" quote; | & > < * ?",
        "ADR-NNNN|ADR-MMMM",
    ):
        data = copy.deepcopy(original)
        next(i for i in data["writes"] if i["name"] == "decisions")["placeholder"] = value
        block = save_blocks(api.render_template(mutated(api, data), "default"))[0]
        prefix = "python3 plugins/saga/scripts/saga.py save"
        assert block.startswith(prefix), "rendered example changed the executable"
        # Only our controlled fixture is interpreted. The function records arguments;
        # it neither selects a documentation-supplied executable nor runs Saga.
        command = "capture() { printf '%s\\0' \"$@\"; };\n" + block.replace(prefix, "capture", 1)
        result = subprocess.run(["bash", "-c", command], capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        args = result.stdout.decode().split("\0")[:-1]
        assert args == shlex.split(block.replace("\\\n", " "))[3:]
        assert args[args.index("--decisions") + 1] == value
        assert "--orchestration-recommended" in args
        assert not marker.exists(), "placeholder executed shell code"


def test_contract_rejects_corrupting_structure(contract_api: ModuleType, tmp_path: Path) -> None:
    api = contract_api
    original = api.load().data
    for value in (api.markers("PLAN SAVE EXAMPLES: default")[1], "<!--", "-->"):
        data = copy.deepcopy(original)
        next(i for i in data["writes"] if i["name"] == "plan_path")["placeholder"] = value
        with pytest.raises(api.ContractError, match="plan_path.*HTML"):
            mutated(api, data)
    data = copy.deepcopy(original)
    data["templates"].append(
        {"id": "contradiction", "fixed": {"destination": "pr", "deploy_autonomy": "auto"}}
    )
    with pytest.raises(api.ContractError, match="contradiction.*condition is false"):
        mutated(api, data)
    data = copy.deepcopy(original)
    moved = next(i for i in data["writes"] if i["name"] == "destination")
    data["writes"].remove(moved)
    moved.pop("when")
    data["identity"].append(moved)
    with pytest.raises(api.ContractError, match="identity.*derive_saga_id"):
        mutated(api, data)
    tree(api, tmp_path)
    reference = "comment --> leak.md"
    (tmp_path / reference).write_text("exists")
    data = copy.deepcopy(original)
    data["effort_honoring"]["reference"] = reference
    with pytest.raises(api.ContractError, match="effort_honoring.*reference"):
        api.load(root=tmp_path, text=yaml.safe_dump(data))
    skill, spec = (ROOT / api.SKILL).read_text(), (ROOT / api.SPEC).read_text()
    begin, end = api.markers("EFFORT HONORING NOTE")
    start, stop = api.region_span(skill, "EFFORT HONORING NOTE")
    nested = skill[:start] + skill[stop:]
    default_end = api.markers("PLAN SAVE EXAMPLES: default")[1]
    nested = nested.replace(default_end, begin + "\n" + end + "\n" + default_end)
    with pytest.raises(api.ContractError, match="generated regions.*overlap"):
        api.rendered_documents(api.load(), nested, spec)

    for delimiter in ("<<<<<<< ours", "=======", ">>>>>>> theirs", "||||||| base"):
        for path in (api.SKILL, api.SPEC):
            with pytest.raises(api.ContractError, match="merge conflict.*entire conflict"):
                api.rendered_documents(
                    api.load(),
                    skill + ("\n" + delimiter if path == api.SKILL else ""),
                    spec + ("\n" + delimiter if path == api.SPEC else ""),
                )


def test_contract_cli_reports_operation_and_checkout(
    contract_api: ModuleType, tmp_path: Path
) -> None:
    api = contract_api
    tree(api, tmp_path)
    for command in (("validate",), ("render", "--check"), ("render", "--write")):
        result = cli(api, tmp_path, *command)
        assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
        assert json.loads(result.stdout)["root"] == str(tmp_path.resolve())
    for args in ((), ("render",), ("--root", "", "validate")):
        result = cli(api, tmp_path, *args)
        detail = json.loads(result.stdout)
        assert result.returncode == 2 and not result.stderr
        assert detail["code"] == "usage" and detail["file"] is None and "--help" in detail["error"]
    engine = tmp_path / "plugins/saga/scripts/saga.py"
    original_engine = engine.read_text()
    for content in (
        "undefined_name",
        "raise RuntimeError('broken import')",
        "raise ValueError('broken import')",
        original_engine.replace("class Saga:", "class RemovedSaga:"),
    ):
        engine.write_text(content)
        result = cli(api, tmp_path, "validate")
        detail = json.loads(result.stdout)
        assert result.returncode == 2 and not result.stderr
        assert detail["code"] == "engine" and detail["file"] == str(engine.relative_to(tmp_path))
        assert "restore" in detail["error"]
    engine.write_text(original_engine)
    raw = (tmp_path / api.CONTRACT).read_text()
    observed = []
    for schema in ("plan_save_contract.v1", "plan_save_contract.v99"):
        (tmp_path / api.CONTRACT).write_text(raw.replace(api.SCHEMA, schema))
        result = cli(api, tmp_path, "validate")
        detail = json.loads(result.stdout)
        assert result.returncode == 2 and detail["code"] == "schema_version"
        assert schema in detail["error"]
        observed.append(detail["error"])
    assert "migrate this obsolete carrier" in observed[0]
    assert "matching tool revision" in observed[1]
    assert "migrate" not in observed[1]
    for bad in (raw + "\nextra: " + "x" * 200_000, "[" * 2000 + "]" * 2000):
        (tmp_path / api.CONTRACT).write_text(bad)
        result = cli(api, tmp_path, "validate")
        assert result.returncode == 2 and not result.stderr
        detail = json.loads(result.stdout)
        assert detail["file"] == str(api.CONTRACT) and len(result.stdout) < 1000
        assert "x" * 1000 not in result.stdout
    (tmp_path / api.CONTRACT).write_text(raw)
    for path in (api.SKILL, api.SPEC):
        original = (tmp_path / path).read_bytes()
        (tmp_path / path).write_bytes(b"\xff invalid UTF-8")
        result = cli(api, tmp_path, "render", "--write")
        detail = json.loads(result.stdout)
        assert result.returncode == 2 and detail["code"] == "syntax"
        assert detail["file"] == str(path) and detail["entry"] == "encoding"
        (tmp_path / path).write_bytes(original)
    engine.unlink()
    engine.symlink_to(ROOT / "plugins/saga/scripts/saga.py")
    result = cli(api, tmp_path, "validate")
    detail = json.loads(result.stdout)
    assert result.returncode == 2 and detail["code"] == "engine"
    assert "escapes" in detail["error"]
    engine.unlink()
    engine.write_text(original_engine)
    (tmp_path / api.CONTRACT).unlink()
    result = cli(api, tmp_path, "validate")
    detail = json.loads(result.stdout)
    assert result.returncode == 2 and detail["code"] == "filesystem"
    assert detail["file"] == str(tmp_path / api.CONTRACT) and "restore" in detail["error"]


def test_contract_save_workspace_is_contained(contract_api: ModuleType, tmp_path: Path) -> None:
    api = contract_api
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    direct = SaveProbe(api, ROOT)

    def forbidden_save(*args: object, **kwargs: object) -> None:
        raise AssertionError("save was reached before rejecting an escaping identity")

    # A deliberately bypassed containment guard must fail without performing the
    # very out-of-workspace write this negative control is designed to prevent.
    direct.engine.save = forbidden_save
    for flags in (
        {"kind": "issue", "id": "../../../../../../escaped"},
        {"id": "../../../../../../escaped"},
        {"kind": "task", "id": "safe", "saga_id": str(outside / "escaped")},
    ):
        with pytest.raises(AssertionError, match="identity escapes its temporary workspace"):
            save_tick(workspace, flags)
        with pytest.raises(AssertionError, match="identity escapes its temporary workspace"):
            direct(workspace, flags)
        assert not (tmp_path / "escaped").exists() and not list(outside.iterdir())
    # Slugified task IDs stay valid; this is path containment, not a text ban.
    tick, _ = save_tick(workspace, {"kind": "task", "id": "area/topic"})
    assert tick["id"] == "area/topic" and tick["saga_id"] == "task-area-topic"
    linked_workspace = tmp_path / "linked"
    linked_workspace.mkdir()
    engine = api.module(ROOT, "plugins/saga/scripts/saga.py", "SAGAS_DIR")
    target = linked_workspace / engine.SAGAS_DIR
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AssertionError, match="identity escapes its temporary workspace"):
        save_tick(linked_workspace, {"kind": "task", "id": "safe"})
    with pytest.raises(AssertionError, match="identity escapes its temporary workspace"):
        direct(linked_workspace, {"kind": "task", "id": "safe"})
    assert not list(outside.iterdir())
    # The edit-time tool must exercise issue IDs even when the example kind is an enum.
    checkout = tmp_path / "checkout"
    tree(api, checkout)
    data = api.load().data
    next(i for i in data["identity"] if i["name"] == "id")["placeholder"] = (
        "../../../../../../escaped"
    )
    (checkout / api.CONTRACT).write_text(yaml.safe_dump(data, sort_keys=False))
    before = {p: (checkout / p).read_bytes() for p in (api.SKILL, api.SPEC)}
    for mode in (("validate",), ("render", "--write")):
        result = cli(api, checkout, *mode)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "identity escapes" in json.loads(result.stdout)["error"]
        assert before == {p: (checkout / p).read_bytes() for p in before}


def test_contract_cli_without_pytest(contract_api: ModuleType, tmp_path: Path) -> None:
    """Offline docs editing uses only Python/PyYAML, including optimized Python."""
    api = contract_api
    checkout = tmp_path / "checkout"
    tree(api, checkout)
    assert not (checkout / "tests").exists()
    environment = tmp_path / "python"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    python = environment / "bin/python"
    site = Path(
        subprocess.check_output(
            [str(python), "-I", "-c", 'import sysconfig; print(sysconfig.get_path("purelib"))'],
            text=True,
        ).strip()
    )
    shutil.copytree(Path(yaml.__file__).parent, site / "yaml")
    absent = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            'import importlib.util; import yaml; assert importlib.util.find_spec("pytest") is None',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert absent.returncode == 0, absent.stdout + absent.stderr
    script = checkout / "plugins/saga/scripts/plan_save_contract.py"

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(python), "-I", "-O", str(script), "--root", str(checkout), *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

    for args in (("validate",), ("render", "--check"), ("render", "--write")):
        result = run(*args)
        assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
        assert json.loads(result.stdout)["root"] == str(checkout.resolve())
    assert not (checkout / ".claude").exists(), "proof wrote Saga state into the checkout"
    originals = {path: (checkout / path).read_bytes() for path in (api.SKILL, api.SPEC)}
    contract_path = checkout / api.CONTRACT
    raw = contract_path.read_text()
    for old, new in (
        ("name: orchestration_recommended", "name: next_step"),
        ("equals: nonprod-deploy", "equals: pr"),
        ("agent: proxy", "agent: native"),
        ("value: complete", "value: pending"),
    ):
        assert old in raw
        contract_path.write_text(raw.replace(old, new))
        result = run("render", "--write")
        assert result.returncode == 2, result.stdout + result.stderr
        if old == "value: complete":
            detail = json.loads(result.stdout)
            assert detail["file"] == str(api.CONTRACT)
            assert (
                detail["entry"] == "writes / saved examples" and "phase_status" in detail["error"]
            )
        assert originals == {path: (checkout / path).read_bytes() for path in originals}
    contract_path.write_text(raw)
    # Factual sentences are checked independently even if renderer and output agree.
    code = script.read_text()
    for old, new, diagnostic in (
        (
            "effort already rides on real controls",
            "effort never rides on real controls",
            "factual clauses differ",
        ),
        (
            "derived from an explicit mode flag",
            "derived on every save",
            "operator-choice derivation",
        ),
        (
            "python3 plugins/saga/scripts/saga.py save",
            "python3 /tmp/not-the-checkout/saga.py save",
            "canonical saga.py save command",
        ),
    ):
        false = code.replace(old, new)
        assert false != code
        script.write_text(false)
        result = run("render", "--write")
        assert result.returncode == 2 and diagnostic in result.stdout, result.stdout
        assert originals == {path: (checkout / path).read_bytes() for path in originals}
        script.write_text(code)
    result = run("validate")
    assert result.returncode == 0, result.stdout + result.stderr


PROOF = "plugins/saga/scripts/plan_save_proof.py"
_ANNOTATIONS = "from __future__ import annotations"
_VERIFY_DOC = (
    '    """Prove candidate facts and saved semantics without loading tests or launching pytest."""'
)


# ---------------------------------------------------------------------------
# Plan-save contract boundary guards, restored. Issue 1030's sweeps took these five with the tests
# of removed modules, which was wrong: they guard the contract CLI's failure envelopes -- a missing
# PyYAML, a BaseException from checkout code, engine resolution, conflict recovery, and the proof
# CLI staying inert under the loader. None of that is touched by the removals, and four canary
# entries name them.
# ---------------------------------------------------------------------------


def test_contract_cli_envelopes_a_missing_pyyaml(contract_api: ModuleType, tmp_path: Path) -> None:
    """An absent PyYAML stays inside the documented envelope (issue #997).

    The tool used to import PyYAML at module scope, which is outside every handler it owns: a
    machine without PyYAML got a traceback, empty stdout and exit 1 -- the code the docstring
    reserves for drift, so a broken interpreter was indistinguishable from a real documentation
    failure. `--help` broke the same way, and it is the one invocation the docstring exempts.

    The interpreter here genuinely lacks PyYAML rather than carrying a module that raises on
    import. A stub proves the symptom; only a real absence proves the repair.
    """
    api = contract_api
    checkout = tmp_path / "checkout"
    tree(api, checkout)
    environment = tmp_path / "python"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    python = environment / "bin/python"
    absent = subprocess.run(
        [str(python), "-I", "-c", 'import importlib.util; assert importlib.util.find_spec("yaml")'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert absent.returncode != 0, "this environment can import PyYAML; the guard proves nothing"
    script = checkout / SCRIPT

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(python), "-I", str(script), "--root", str(checkout), *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

    originals = {path: (checkout / path).read_bytes() for path in (api.SKILL, api.SPEC)}
    for args in (("validate",), ("render", "--check"), ("render", "--write")):
        result = run(*args)
        assert result.returncode == 2, (
            f"{args}: expected the documented refusal exit 2, got {result.returncode}"
            f"\n{result.stdout}\n{result.stderr}"
        )
        assert not result.stderr, result.stderr
        payload = json.loads(result.stdout)
        assert payload["outcome"] == "invalid", payload
        assert payload["code"] == "engine", payload
        assert payload["entry"] == "python dependency", payload
        assert payload["file"] == str(SCRIPT), payload
        assert "PyYAML" in str(payload["error"]), payload
    assert originals == {path: (checkout / path).read_bytes() for path in originals}, (
        "a refused render wrote to an owned document"
    )

    # --help is the documented exemption, and it must survive an interpreter with no PyYAML at all:
    # argparse runs before any YAML is touched.
    usage = subprocess.run(
        [str(python), "-I", str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert usage.returncode == 0, usage.stdout + usage.stderr
    assert not usage.stderr, usage.stderr
    assert usage.stdout.startswith("usage: plan_save_contract.py"), usage.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(usage.stdout)

    # The same checkout under this suite's own interpreter, which has PyYAML, is unaffected.
    clean = cli(api, checkout, "validate")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert json.loads(clean.stdout)["outcome"] == "valid"


def test_contract_cli_envelopes_baseexception_from_checkout_code(
    contract_api: ModuleType, tmp_path: Path
) -> None:
    """Checkout code raising a BaseException stays inside the JSON envelope (issue #996).

    The tool executes the checkout named by --root in-process. `except Exception` does not
    cover SystemExit or KeyboardInterrupt, so either one used to leave a caller parsing stdout
    with no JSON at all and an exit code outside the documented 0/1/2. Two seams can raise:
    loading the proof through runpy, and calling the loaded verify(). Both are probed, because
    the second one is reachable only after the first one is guarded.
    """
    api = contract_api
    checkout = tmp_path / "checkout"
    tree(api, checkout)
    proof = checkout / PROOF
    original = proof.read_text()
    assert _ANNOTATIONS in original and _VERIFY_DOC in original, (
        f"{PROOF}: probe anchors are gone; re-derive them from the current file"
    )

    def refusal(mutation: str, *, entry: str, code: str = "engine") -> dict[str, object]:
        proof.write_text(mutation)
        result = cli(api, checkout, "validate")
        proof.write_text(original)
        assert result.returncode == 2, (
            f"{entry}: expected the documented refusal exit 2, "
            f"got {result.returncode}\n{result.stdout}\n{result.stderr}"
        )
        payload: dict[str, object] = json.loads(result.stdout)
        assert payload["outcome"] == "invalid"
        assert payload["code"] == code and payload["entry"] == entry, payload
        assert payload["file"] == PROOF, payload
        return payload

    # Seam one: the BaseException escapes while runpy loads the file.
    refusal(
        original.replace(_ANNOTATIONS, _ANNOTATIONS + "\nimport sys\nsys.exit(7)", 1),
        entry="engine import",
    )
    refusal(
        original.replace(_ANNOTATIONS, _ANNOTATIONS + "\nraise KeyboardInterrupt('probe')", 1),
        entry="engine import",
    )
    # Seam two: the file loads, and the BaseException escapes while verify() runs.
    refusal(
        original.replace(_VERIFY_DOC, _VERIFY_DOC + "\n    import sys; sys.exit(9)", 1),
        entry="engine proof",
    )
    # A ContractError from the proof keeps its own diagnosis; it is not relabelled an engine fault.
    diagnosed = refusal(
        original.replace(
            _VERIFY_DOC,
            _VERIFY_DOC
            + '\n    api.fail("probe entry", "probe reason",'
            + f' source="{PROOF}", code="verification")',
            1,
        ),
        entry="probe entry",
        code="verification",
    )
    assert "probe reason" in str(diagnosed["error"]), diagnosed

    # The unmutated checkout is untouched by the guard.
    clean = cli(api, checkout, "validate")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert json.loads(clean.stdout)["outcome"] == "valid"

    # --help is the one documented exemption, and it only works because main()'s handler stays
    # narrow: argparse raises SystemExit(0) from inside that try. A broad handler there would
    # print a JSON refusal at exit 2 instead of usage at exit 0.
    usage = subprocess.run(
        [sys.executable, str(ROOT / "plugins/saga/scripts/plan_save_contract.py"), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert usage.returncode == 0, usage.stdout + usage.stderr
    assert usage.stdout.startswith("usage: plan_save_contract.py"), usage.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(usage.stdout)


def test_contract_cli_resolves_the_engine_from_the_checkout(
    contract_api: ModuleType, tmp_path: Path
) -> None:
    """The effort engine comes from --root, never from the operator's installed plugins.

    fleet_commons_shim.resolve_root() falls through to ~/.claude/plugins and the plugin
    cache when a checkout carries no marketplace manifest, which is every temporary
    checkout here. Without the binding this suite passes on a developer machine that has
    fleet-core installed and fails everywhere else, so the run below scrubs HOME.
    """
    api = contract_api
    checkout = tmp_path / "checkout"
    tree(api, checkout)
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
    }
    environment.pop(api.FLEET_ROOT_ENV, None)
    script = checkout / "plugins/saga/scripts/plan_save_contract.py"

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), "--root", str(checkout), "validate"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["outcome"] == "valid"

    # Prove the checkout's own copy is what answered: remove it and the tool must refuse,
    # not quietly fall back to whatever fleet-core the machine has installed.
    shutil.rmtree(checkout / api.FLEET_CORE / "scripts")
    refused = run()
    assert refused.returncode == 2, refused.stdout + refused.stderr
    payload = json.loads(refused.stdout)
    assert payload["code"] == "engine" and payload["file"] == api.RIDER


PROOF = "plugins/saga/scripts/plan_save_proof.py"
_ANNOTATIONS = "from __future__ import annotations"
_VERIFY_DOC = (
    '    """Prove candidate facts and saved semantics without loading tests or launching pytest."""'
)


def test_contract_conflict_recovery(contract_api: ModuleType, tmp_path: Path) -> None:
    """Following the runbook removes the entire conflict before a successful render."""
    api = contract_api
    tree(api, tmp_path)
    path = tmp_path / api.SKILL
    original = path.read_text()
    begin, end = api.region_span(original, "PLAN SAVE EXAMPLES: default")
    region = original[begin:end]
    conflict = "<<<<<<< ours\n" + region + "\n=======\n" + region + "\n>>>>>>> theirs\n"
    path.write_text(original[:begin] + conflict + original[end:])
    result = cli(api, tmp_path, "render", "--write")
    assert result.returncode == 2 and "entire conflict" in json.loads(result.stdout)["error"]
    assert conflict in path.read_text()
    # Resolve the entire hunk to one region; surrounding prose remains byte-identical.
    path.write_text(path.read_text().replace(conflict, region))
    result = cli(api, tmp_path, "render", "--write")
    assert result.returncode == 0, result.stdout + result.stderr
    assert path.read_text() == original
    result = cli(api, tmp_path, "render", "--check")
    assert result.returncode == 0 and json.loads(result.stdout)["outcome"] == "clean"


def test_proof_cli_describes_itself_and_stays_inert_under_the_loader(
    contract_api: ModuleType, tmp_path: Path
) -> None:
    """The proof names itself and its runnable command, and the loader never fires it (#998).

    `plan_save_proof.py` had no entrypoint at all, so every direct invocation -- `--help` and a
    guessed subcommand alike -- exited 0 and printed nothing. Silence at a success code is the
    sharp edge: a mistyped invocation was indistinguishable from a passing run.

    The proof is not runnable on its own (`verify()` needs the contract module's globals, a loaded
    contract and a rendered candidate), so the entrypoint describes and refuses rather than
    duplicating `plan_save_contract.py validate` and bypassing its tool-revision check.

    Standard output stays empty on every refusal. The contract tool's callers parse standard
    output as JSON, and this file must never emit anything they could mistake for that envelope.

    The `--help` probe runs on an interpreter with no PyYAML at all: the import moved to its point
    of use so the entrypoint this test creates is not born with issue #997's defect. The
    interpreter's genuine lack of PyYAML is asserted before it proves anything.

    The last probe is positive, not negative. `runpy.run_path` names the module it loads
    `<run_path>`, so a `__main__` guard cannot fire under `plan_save_contract.py`'s loader -- and
    if it ever did, issue #996's guard would convert the `SystemExit` into a tidy-looking refusal
    blaming the engine, hiding the misfire rather than surfacing it.
    """
    api = contract_api
    proof = ROOT / PROOF

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(proof), *args],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )

    # R1: --help says what the file is and names the command that actually runs it.
    usage = run("--help")
    assert usage.returncode == 0, usage.stdout + usage.stderr
    assert usage.stdout.startswith("usage: plan_save_proof.py"), usage.stdout
    assert str(SCRIPT) in usage.stdout, usage.stdout
    assert "validate" in usage.stdout, usage.stdout
    assert not usage.stderr, usage.stderr

    # R2, bare invocation: the entrypoint's own guidance, naming the runnable command.
    bare = run()
    assert bare.returncode == 2, f"{bare.returncode}\n{bare.stdout}\n{bare.stderr}"
    assert bare.stdout == "", bare.stdout
    assert str(SCRIPT) in bare.stderr, bare.stderr

    # R2, malformed arguments: argparse's own usage. Still exit 2, still silent on standard output.
    for args in (("--not-a-flag",), ("validate", "--root", ".")):
        refused = run(*args)
        assert refused.returncode == 2, f"{args}: {refused.returncode}\n{refused.stderr}"
        assert refused.stdout == "", f"{args}: {refused.stdout!r}"
        assert "plan_save_proof.py" in refused.stderr, f"{args}: {refused.stderr!r}"

    # R3: --help survives an interpreter that genuinely cannot import PyYAML.
    environment = tmp_path / "python"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    python = environment / "bin/python"
    absent = subprocess.run(
        [str(python), "-I", "-c", 'import importlib.util; assert importlib.util.find_spec("yaml")'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert absent.returncode != 0, "this environment can import PyYAML; the guard proves nothing"
    bare_interpreter = subprocess.run(
        [str(python), "-I", str(proof), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bare_interpreter.returncode == 0, bare_interpreter.stdout + bare_interpreter.stderr
    assert bare_interpreter.stdout.startswith("usage: plan_save_proof.py"), bare_interpreter.stdout

    # R4: the loader still loads this file as a library, so a clean checkout validates unchanged.
    checkout = tmp_path / "checkout"
    tree(api, checkout)
    clean = cli(api, checkout, "validate")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert json.loads(clean.stdout)["outcome"] == "valid", clean.stdout
