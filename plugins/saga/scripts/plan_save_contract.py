#!/usr/bin/env python3
"""Check or render Plan documentation in an explicit repository checkout.

Usage and ownership: plugins/saga/references/plan-save-contract.md.
Every invocation except --help returns JSON: 0 success, 1 drift, 2 refusal.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import inspect
import json
import os
import re
import runpy
import shlex
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

# PyYAML is imported by yaml_module() at first use, deliberately not here -- see its docstring.

ROOT = Path(__file__).resolve().parents[3]
TOOL = Path("plugins/saga/scripts/plan_save_contract.py")
CONTRACT = Path("plugins/saga/references/plan-save-contract.yaml")
SKILL = Path("plugins/saga/skills/plan/SKILL.md")
SPEC = Path("plugins/saga/references/saga-spec.md")
SCHEMA = "plan_save_contract.v3"
RIDER = "plugins/fleet-core/scripts/fleet_commons/effort_rider.py"
FLEET_CORE = "plugins/fleet-core"
FLEET_ROOT_ENV = "FLEET_COMMONS_ROOT"
EFFORT_REFERENCE = Path("plugins/fleet-core/references/staffing.md")


class ContractError(ValueError):
    def __init__(self, source: object, entry: str, reason: str, code: str = "invalid_contract"):
        self.source = str(source) if source is not None else None
        self.entry, self.code = entry, code
        super().__init__(f"{source}: {entry}: {reason}")


def fail(
    entry: str, reason: str, *, source: object = CONTRACT, code: str = "invalid_contract"
) -> NoReturn:
    raise ContractError(source, entry, reason, code)


def keys(value: Any, expected: set[str], entry: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        actual = list(value)[:12] if isinstance(value, dict) else type(value).__name__
        fail(entry, f"expected exactly these keys: {sorted(expected)}; got {str(actual)[:240]}")


@contextlib.contextmanager
def fleet_root(root: Path) -> Iterator[None]:
    """Resolve fleet-core from the target checkout for the duration of an engine load.

    Older fleet-core builds resolved their root from this variable before they read the
    operator's installed plugins. The fleet-core this catalog ships loads a sibling from
    the file's own directory, so the variable is unused by that build. It stays set so a
    checkout that still honors it validates against --root instead of against whatever
    that machine has installed.
    """
    previous = os.environ.get(FLEET_ROOT_ENV)
    os.environ[FLEET_ROOT_ENV] = str((root / FLEET_CORE).resolve())
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(FLEET_ROOT_ENV, None)
        else:
            os.environ[FLEET_ROOT_ENV] = previous


@contextlib.contextmanager
def checkout_code(path: str, entry: str, reason: str) -> Iterator[None]:
    """Keep a BaseException raised by checkout code inside this tool's JSON envelope.

    The checkout named by --root is executed in-process, so whatever it raises lands here.
    `except Exception` does not cover SystemExit or KeyboardInterrupt, and either one escaping
    leaves a caller parsing stdout with no JSON at all and an exit code outside the documented
    0/1/2 (issue #996). A ContractError passes through untouched: the checkout already diagnosed
    itself and relabelling that as an engine fault would lose the diagnosis.

    An interrupt arriving while checkout code runs is converted rather than re-raised. A
    KeyboardInterrupt raised BY the checkout is indistinguishable here from one delivered by the
    terminal, so re-raising would leave the reported defect unfixed. The window is deliberately
    only as wide as the checkout's own execution.

    This is the only correct home for the repair. main()'s handler must stay `except Exception`,
    because argparse raises SystemExit(0) for --help from inside that same try: widen it and
    --help returns a JSON refusal at exit 2 instead of usage at exit 0.
    """
    try:
        yield
    except ContractError:
        raise
    except BaseException as exc:
        fail(entry, f"{exc}; {reason}", source=path, code="engine")


def module(root: Path, path: str, *members: str) -> Any:
    try:
        target = (root / path).resolve()
        if not target.is_relative_to(root.resolve()):
            raise ImportError("engine path escapes checkout")
        with fleet_root(root):
            result = SimpleNamespace(**runpy.run_path(str(target)))
        for member in members:
            getattr(result, member)
        return result
    # BaseException, not Exception: SystemExit and KeyboardInterrupt from the loaded file used to
    # escape this tool's JSON envelope entirely (issue #996, see checkout_code above). Ordinary
    # exceptions keep the treatment they have always had, ContractError included -- this loader
    # has always rewritten them into the message below -- so no documented path changes.
    except BaseException as exc:
        fail(
            "engine import",
            f"{exc}; restore this checkout and its Python dependencies",
            source=path,
            code="engine",
        )


def yaml_module() -> Any:
    """Import PyYAML at first use, so a machine without it gets the documented refusal.

    Deliberately not a module-level `import yaml`. A module-scope import sits outside every
    handler this tool owns, so a missing PyYAML killed the process with a raw traceback, empty
    stdout and exit 1 -- the code the docstring reserves for drift, which made a broken
    interpreter indistinguishable from a real documentation failure -- and it took `--help` down
    with it, the one invocation the docstring exempts (issue #997).

    Called from the parsing path, the failure is an ordinary ImportError inside main()'s existing
    `try`, which already knows how to answer, and argparse has served `--help` long before this
    runs. Do not hoist this back to the preamble.
    """
    try:
        import yaml
    except ImportError as exc:
        fail(
            "python dependency",
            f"{exc}; install PyYAML (pyyaml>=6.0) into the interpreter running this tool",
            source=TOOL,
            code="engine",
        )
    return yaml


def unique_loader(yaml: Any) -> Any:
    """Build the duplicate-key-rejecting loader against an already-imported PyYAML.

    Built here rather than at module scope because the class statement needs the real
    yaml.SafeLoader object at class-creation time. That is why yaml_module() defers the import
    instead of leaving a `yaml = None` sentinel at module scope: a sentinel would simply move the
    crash from the import down into this class statement (issue #997).
    """

    class UniqueLoader(yaml.SafeLoader):
        def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in result:
                    fail(
                        f"line {key_node.start_mark.line + 1} key {key!r}",
                        "mapping keys must be unique strings; remove the duplicate/invalid entry",
                    )
                result[key] = self.construct_object(value_node, deep=deep)
            return result

    return UniqueLoader


@dataclass
class Contract:
    data: dict[str, Any]
    root: Path


def load(*, root: Path = ROOT, text: str | None = None) -> Contract:
    """Read structure; the mandatory CLI proof binds values to engine and output."""
    yaml = yaml_module()
    raw = (root / CONTRACT).read_text() if text is None else text
    # Aliases earn nothing in this small carrier. Reject before constructing any graph.
    for token in yaml.scan(raw):
        if isinstance(token, yaml.AliasToken):
            fail(
                f"line {token.start_mark.line + 1} alias {token.value}",
                "aliases are unsupported; spell out this entry",
            )
    data = yaml.load(raw, Loader=unique_loader(yaml))  # nosec B506: subclass of SafeLoader; no object constructors
    schema = data.get("schema") if isinstance(data, dict) else None
    if schema != SCHEMA:
        fail(
            "schema",
            f"observed {str(schema)[:80]!r}, expected {SCHEMA}; "
            + (
                "migrate this obsolete carrier using the runbook"
                if schema in ("plan_save_contract.v1", "plan_save_contract.v2")
                else "restore the expected carrier or use its matching tool revision"
            ),
            code="schema_version"
            if isinstance(schema, str) and schema.startswith("plan_save_contract.")
            else "schema_family",
        )
    keys(data, {"schema", "identity", "writes", "templates", "effort_honoring"}, "contract")
    saga = module(
        root, "plugins/saga/scripts/saga.py", "_add_save_parser", "Saga", "derive_saga_id"
    )
    names: set[str] = set()
    for section in ("identity", "writes", "templates"):
        items = data[section]
        if not isinstance(items, list) or not items:
            fail(section, "expected a nonempty list")
        seen: set[str] = set()
        for index, item in enumerate(items):
            entry = f"{section}[{index}]"
            if not isinstance(item, dict):
                fail(entry, "expected a mapping")
            name = item.get("id" if section == "templates" else "name")
            entry += f" ({name!r})"
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                fail(entry, "expected an identifier")
            if name in seen or (section != "templates" and name in names):
                fail(entry, "duplicate entry; keep exactly one")
            seen.add(name)
            if section == "templates":
                keys(item, {"id", "fixed"}, entry)
                if not isinstance(item["fixed"], dict):
                    fail(entry + ".fixed", "expected a mapping of fields to choices")
                for field, value in item["fixed"].items():
                    if field not in names:
                        fail(entry + ".fixed", f"unknown field {field!r}")
                    string(value, entry + ".fixed")
                    source = next(
                        i for i in data["identity"] + data["writes"] if i["name"] == field
                    )
                    if "value" in source and value != source["value"]:
                        fail(
                            entry + ".fixed",
                            f"{field} has a contract constant; remove the conflicting override",
                        )
                continue
            names.add(name)
            value_key = "value" if "value" in item else "placeholder"
            keys(item, {"name", value_key} | ({"when"} if section == "writes" else set()), entry)
            string(item[value_key], entry + "." + value_key)
    for item in data["writes"]:
        when = item["when"]
        if when != "always":
            entry = f"writes ({item['name']!r}).when"
            keys(when, {"field", "equals"}, entry)
            if (
                not isinstance(when["field"], str)
                or when["field"] not in names
                or when["field"] == item["name"]
            ):
                fail(entry, "condition must reference another declared field")
            string(when["equals"], entry + ".equals")
            for template in data["templates"]:
                fixed = template["fixed"]
                if (
                    item["name"] in fixed
                    and when["field"] in fixed
                    and fixed[when["field"]] != when["equals"]
                ):
                    fail(
                        f"templates ({template['id']!r}).fixed",
                        f"{item['name']} is fixed while its condition is false; remove that fixed value",
                    )
    identity = {name.rstrip("_") for name in inspect.signature(saga.derive_saga_id).parameters}
    if {item["name"] for item in data["identity"]} != identity:
        fail(
            "identity",
            f"must match derive_saga_id inputs {sorted(identity)}; place payload fields in writes",
        )
    effort = data["effort_honoring"]
    keys(effort, {"spawn_kinds"}, "effort_honoring")
    rider = module(root, RIDER, "inject_effort", "SPAWN_KINDS", "EFFORTS", "EFFORT_RIDER")
    keys(effort["spawn_kinds"], set(rider.SPAWN_KINDS), "effort_honoring.spawn_kinds")
    if not (root / EFFORT_REFERENCE).is_file():
        fail("reference", "restore the honoring convention", source=EFFORT_REFERENCE)
    return Contract(data, root)


def string(value: Any, entry: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(c in value for c in ("\n", "\r", "\x00", "<!--", "-->"))
    ):
        fail(entry, "expected a nonempty single-line string without HTML comment markers")


def render_consumer_row(contract: Contract) -> str:
    cells = []
    for item in contract.data["writes"]:
        token = item["name"] + ("=" + item["value"] if "value" in item else "")
        cell = f"`{token}`"
        if item["when"] != "always":
            when = item["when"]
            cell += f" (only when `{when['field']}={when['equals']}`)"
        cells.append(cell)
    cells.append(
        "`orchestration_operator_choice` (derived from an explicit mode flag unless an explicit "
        "choice is supplied; omitting both preserves the prior choice or starts empty)"
    )
    return "| **/plan** | `scan` (§2.3) | " + ", ".join(cells) + ". |"


def render_template(contract: Contract, template_id: str) -> str:
    template = next(t for t in contract.data["templates"] if t["id"] == template_id)
    flags, bullets = [], []
    for item in contract.data["identity"] + contract.data["writes"]:
        name = item["name"]
        value = template["fixed"].get(name, item.get("value", item.get("placeholder")))
        flag = f"--{name.replace('_', '-')} {shlex.quote(value)}"
        when = item.get("when", "always")
        if when != "always":
            fixed = template["fixed"].get(when["field"])
            if fixed is None:
                bullets.append(
                    f"- `{flag}` only when `--{when['field'].replace('_', '-')} {when['equals']}`."
                )
                continue
            if fixed != when["equals"]:
                continue
        flags.append(flag)
    lines = [
        f"**Example: {template_id}**",
        "",
        "```bash",
        "python3 plugins/saga/scripts/saga.py save \\",
    ]
    lines += ["  " + flag + (" \\" if i < len(flags) - 1 else "") for i, flag in enumerate(flags)]
    return "\n".join(lines + ["```", "", *bullets]).rstrip()


def render_effort_note(contract: Contract) -> str:
    rider = module(contract.root, RIDER, "inject_effort")
    parameters = ", ".join(inspect.signature(rider.inject_effort).parameters)
    lines = [
        f"The honoring seam is `fleet_commons.effort_rider.{rider.inject_effort.__name__}({parameters})`."
    ]
    kinds = contract.data["effort_honoring"]["spawn_kinds"]
    for mechanism, sentence in (
        (
            "native",
            "effort already rides on real controls; injecting a rider would double-count it.",
        ),
        (
            "proxy",
            "prepend an `EFFORT_RIDER` directive: a labeled proxy because the Agent tool has no per-call effort parameter.",
        ),
    ):
        group = ", ".join(f"`{kind}`" for kind in sorted(kinds) if kinds[kind] == mechanism)
        lines.append(f"For {group}: {sentence}")
    lines += [
        f"See `{EFFORT_REFERENCE}`.",
        "The proposed tier cell is `<model>/<effort>`: use `tier_resolver.resolve(...).model`",
        "and `tier_resolver.resolve(...).effort` verbatim so dispatch receives both resolved values.",
        "Team Execution A7 uses the same pair and splits on `/`; its older note is tracked by #993.",
    ]
    return region("EFFORT HONORING NOTE", "<!--\n" + "\n".join(lines) + "\n-->")


def markers(name: str) -> tuple[str, str]:
    return f"<!-- BEGIN GENERATED {name} -->", f"<!-- END GENERATED {name} -->"


def region(name: str, body: str) -> str:
    begin, end = markers(name)
    owner = (
        f"<!-- Source: {CONTRACT}; renderer: plugins/saga/scripts/plan_save_contract.py.\n"
        "Do not hand-edit; guard: tests/test_saga_spec_consumer_row.py::test_plan_docs_generated_regions_match_contract. -->"
    )
    return f"{begin}\n{owner}\n{body}\n{end}"


def region_span(text: str, name: str, path: Path = SKILL) -> tuple[int, int]:
    begin, end = markers(name)
    if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) >= text.index(end):
        fail(
            name,
            "expected one ordered marker pair; restore markers from git, or resolve the merge conflict using the maintainer runbook before rendering",
            source=path,
        )
    return text.index(begin), text.index(end) + len(end)


def row_span(text: str) -> tuple[int, int]:
    rows = list(re.finditer(r"^\| \*\*/plan\*\* \|[^\n]*", text, re.MULTILINE))
    if len(rows) != 1:
        fail(
            "/plan consumer row",
            f"found {len(rows)}; restore exactly one row from git",
            source=SPEC,
        )
    return rows[0].span()


def rendered_documents(contract: Contract, skill: str, spec: str) -> dict[Path, str]:
    for path, text in ((SKILL, skill), (SPEC, spec)):
        if re.search(r"(?m)^(?:<{7}|={7}|>{7}|\|{7})(?: |$)", text):
            fail(
                "merge conflict",
                "resolve the entire conflict, including its delimiters, before rendering",
                source=path,
            )
    replacements = []
    for group in ("default", "workflow"):
        name = "PLAN SAVE EXAMPLES: " + group
        examples = [
            render_template(contract, t["id"])
            for t in contract.data["templates"]
            if (t["fixed"].get("orchestration_mode") == "cc-workflows-ultracode")
            == (group == "workflow")
        ]
        replacements.append((*region_span(skill, name), region(name, "\n\n".join(examples))))
    replacements.append((*region_span(skill, "EFFORT HONORING NOTE"), render_effort_note(contract)))
    replacements.sort()
    for left, right in zip(replacements, replacements[1:], strict=False):
        if left[1] > right[0]:
            fail("generated regions", "overlap; restore the markers from git", source=SKILL)
    outside = skill
    for start, end, replacement in reversed(replacements):
        skill = skill[:start] + replacement + skill[end:]
        outside = outside[:start] + "\n" * outside[start:end].count("\n") + outside[end:]
    command = r"(?:python3?\s+)?(?:[\w./-]+/)?saga\.py\s+save"
    if re.search(rf"(?m)^\s*{command}\b|`{command}\s+--", outside):
        fail(
            "save example outside generated regions",
            "add examples to templates in YAML; remove the extra command from the document",
            source=SKILL,
        )
    start, end = row_span(spec)
    return {SKILL: skill, SPEC: spec[:start] + render_consumer_row(contract) + spec[end:]}


def write_documents(
    root: Path, originals: dict[Path, str], rendered: dict[Path, str], changed: list[Path]
) -> None:
    """Stage the batch, roll back I/O failures, and retain backups if rollback fails."""
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    written: list[Path] = []
    try:
        for path in changed:
            for target, content in ((staged, rendered[path]), (backups, originals[path])):
                with tempfile.NamedTemporaryFile(
                    mode="w", dir=(root / path).parent, prefix=".plan-contract-", delete=False
                ) as handle:
                    target[path] = Path(handle.name)
                    handle.write(content)
                target[path].chmod((root / path).stat().st_mode)
        try:
            for path in changed:
                os.replace(staged[path], root / path)
                written.append(path)
        except OSError as exc:
            failed_path = path
            failures = []
            for path in reversed(written):
                try:
                    os.replace(backups[path], root / path)
                except OSError:
                    failures.append(f"{path}: restore {backups.pop(path)} manually")
            fail(
                "filesystem",
                f"{exc}; "
                + (
                    "rollback incomplete: " + "; ".join(failures)
                    if failures
                    else "all changes rolled back; fix filesystem access and retry"
                ),
                source=root / failed_path,
                code="filesystem",
            )
    finally:
        for path in [*staged.values(), *backups.values()]:
            path.unlink(missing_ok=True)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail("usage", message + "; run --help", source=None, code="usage")


def verify_saved_examples(contract: Contract, candidate: dict[Path, str]) -> None:
    """Verify this candidate with the checkout's plain Python proof before any write."""
    if (contract.root / TOOL).read_bytes() != Path(__file__).read_bytes():
        fail(
            "tool revision",
            "run the tool from the target checkout so its verified renderer is the one that writes",
            source=TOOL,
            code="verification",
        )
    # Not TOOL above: that is this script; this is the checkout's proof, a different file.
    proof_path = "plugins/saga/scripts/plan_save_proof.py"
    proof = module(contract.root, proof_path, "verify")
    # Loading the proof is guarded by module(); RUNNING it is the second seam. A BaseException
    # raised here escaped the envelope too, and a ContractError from the proof's own api.fail()
    # keeps its verification diagnosis rather than being relabelled an engine fault (issue #996).
    with checkout_code(proof_path, "engine proof", "restore this checkout's saved-example proof"):
        proof.verify(SimpleNamespace(**globals()), contract, candidate)


def main(argv: list[str] | None = None) -> int:
    root = ROOT
    try:
        parser = Parser(description=__doc__)
        parser.add_argument(
            "--root", default=str(ROOT), help="target checkout (code, YAML and docs together)"
        )
        sub = parser.add_subparsers(dest="command", required=True)
        sub.add_parser("validate", help="check structured input and real saved examples")
        render = sub.add_parser("render", help="check or update generated documentation")
        mode = render.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            "--check", action="store_true", help="report drift as JSON; exit 1 if different"
        )
        mode.add_argument(
            "--write", action="store_true", help="update both docs; roll back on write failure"
        )
        args = parser.parse_args(argv)
        if not args.root.strip():
            parser.error("--root must name a checkout")
        root = Path(args.root).resolve()
        contract = load(root=root)
        originals = {}
        for path in (SKILL, SPEC):
            try:
                originals[path] = (root / path).read_text()
            except UnicodeError as exc:
                fail("encoding", f"{exc}; restore UTF-8 text", source=path, code="syntax")
        rendered = rendered_documents(contract, originals[SKILL], originals[SPEC])
        verify_saved_examples(contract, rendered)
        if args.command == "validate":
            return report(0, root, outcome="valid", schema=SCHEMA)
        changed = [p for p in originals if originals[p] != rendered[p]]
        if args.check:
            diff = "".join(
                "".join(
                    difflib.unified_diff(
                        originals[p].splitlines(True),
                        rendered[p].splitlines(True),
                        fromfile=str(p),
                        tofile=str(p),
                    )
                )
                for p in changed
            )
            return report(
                int(bool(changed)),
                root,
                outcome="drift" if changed else "clean",
                diff=diff,
                changed=list(map(str, changed)),
            )
        write_documents(root, originals, rendered, changed)
        return report(0, root, outcome="rendered", changed=list(map(str, changed)))
    # Exception, deliberately, and not BaseException: argparse raises SystemExit(0) for --help from
    # inside this try, and letting it through is the only reason --help prints usage and exits 0.
    # A BaseException from the checkout is caught where the checkout runs instead -- see
    # checkout_code() and module(). Do not widen this handler (issue #996).
    except Exception as exc:
        if not isinstance(exc, ContractError):
            exc = ContractError(
                getattr(exc, "filename", None) or CONTRACT,
                "load/render",
                str(exc)[:1800] + "; restore readable, valid checkout inputs before retrying",
                "filesystem" if isinstance(exc, OSError) else "syntax",
            )
        return report(
            2,
            root,
            outcome="invalid",
            error=str(exc)[:2000],
            code=exc.code,
            file=exc.source,
            entry=exc.entry,
        )


def report(exit_code: int, root: Path, **detail: Any) -> int:
    print(json.dumps({"root": str(root), **detail}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
