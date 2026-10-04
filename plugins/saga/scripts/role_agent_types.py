#!/usr/bin/env python3
"""What each staffed role of this checkout's active saga run runs as (issue #106).

A harness that can declare a subagent type with its own model and effort asks this script which
types to declare. The answer is one entry per role the roles library briefs: the role's prompt,
read from the library file at call time and never copied, and the model and effort the run is
staffed at. The script reads and prints; it writes nothing.

**When there is no run, the answer is empty.** The active-run rule is ``next_step_context``'s, the
same one the session-start announcement uses: a record exists for the issue this checkout resolves
to, and its ``next_step`` is not empty. With no active run the script answers ``active: false`` and
no types, so a session with no saga run is left exactly as it was.

**Where a role's tier comes from.** The staffing resolver, ``staffing.resolve_role`` from the
build-time bundle, asked from the checkout so its per-repository overlay applies. This script
writes no precedence order of its own: it hands the resolver what the run record holds for the
role in ``run_configuration.staffing_models_and_efforts`` and lets the resolver's one order apply.
A row the operator wrote (a ``staffing_overrides`` answer, or a row marked ``operator_override``)
goes in as the operator's answer; a recorded ``jev_raise`` goes in as the raise, which the
resolver refuses unless it is exactly one step above its base. A row admission filled from the
resolver is simply answered again.

**Which roles.** Every role agent-launcher's roster maps to a roles-library prompt
(``roster.STAFFING_ROLE_TO_ROLE_ID``, imported, never copied), except two. The lens reviewer's
prompt is sliced per lens, so one type cannot carry it. ``merging-worker`` has no prompt at all
(roster's own refusal). A role staffed on a vendor other than ``claude`` is reported as skipped,
never translated. A ``claude`` vendor name is a staffing value here, not harness behaviour: the
script names no harness and no agent type.

**The hosting preamble.** A library prompt is written for a role that runs as its own session and
posts its own handoff comments. Run as an in-session subagent it reports to the session that
dispatched it, which posts every handoff, so a short saga-owned preamble saying so is put in front
of the library text.

Prints one JSON object (``saga_role_agent_types.v1``) and always exits 0, except a usage error
(exit 2). A failure is a named ``error`` beside an empty type list, never a traceback, because the
caller is a hook that must not cost the operator a turn.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import next_step_context  # noqa: E402  (after the sys.path shim, by design)
import run_record  # noqa: E402

SCHEMA = "saga_role_agent_types.v1"

#: This file is ``<saga package root>/scripts/role_agent_types.py``.
SAGA_ROOT = Path(__file__).resolve().parents[1]

#: Names agent-launcher's package root when it is installed somewhere the ladder cannot see.
AGENT_LAUNCHER_ENV = "SAGA_AGENT_LAUNCHER_ROOT"

#: Inside agent-launcher's package root.
ROSTER_SUBPATH = Path("skills") / "agent-launcher" / "scripts" / "roster.py"
ROLES_SUBPATH = Path("roles")

#: The roster role whose prompt is cut per lens.
LENS_ROLE = "lens-reviewer"

#: The vendor whose roles this answer covers.
VENDOR = "claude"

HOSTING_PREAMBLE = """\
# Hosting: an in-session subagent of a saga run

You are running as a subagent inside the session that coordinates this saga run, not as a
session of your own. The role briefing below is written for a role that runs in its own session;
where it differs from this preamble, this preamble wins.

- Your task, the issue, and the run's state come from the brief you were dispatched with. Read
  the run record and the plan it names when you need more.
- Return your result in your role's output contract as your final message. That message is your
  handoff: the coordinating session reads it and records it.
- Do not post comments on the issue or the pull request. Where the briefing tells you to post a
  handoff comment, put that content in your final message instead; the coordinator posts every
  handoff.

---

"""

#: ``resolver(role, cwd, *, answer, jev_raise)`` -> the resolver's decision as a mapping.
Resolver = Callable[..., Mapping[str, Any]]


class RoleTypesError(RuntimeError):
    """A named reason this checkout's types cannot be answered."""


# --------------------------------------------------------------------------- locating the library


def agent_launcher_candidates(
    explicit: Path | None = None, *, env: Mapping[str, str] | None = None
) -> list[Path]:
    """The places agent-launcher's package root may be, in the order they are tried.

    An explicit path, then the environment, then a sibling of this package in a source checkout or
    a folder marketplace, then the newest version beside this package in a versioned install
    layout (``<root>/<package>/<version>/``).
    """
    environ = os.environ if env is None else env
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    if environ.get(AGENT_LAUNCHER_ENV):
        candidates.append(Path(environ[AGENT_LAUNCHER_ENV]))
    candidates.append(SAGA_ROOT.parent / "agent-launcher")
    versions = sorted(
        (p for p in (SAGA_ROOT.parent.parent / "agent-launcher").glob("*") if p.is_dir()),
        key=lambda p: _version_key(p.name),
    )
    if versions:
        candidates.append(versions[-1])
    return candidates


def _version_key(name: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part for part in name.replace("-", ".").split("."))


def locate_agent_launcher(
    explicit: Path | None = None, *, env: Mapping[str, str] | None = None
) -> Path:
    """Return the first candidate that holds the roster helper, or refuse naming every rung."""
    tried = agent_launcher_candidates(explicit, env=env)
    for root in tried:
        if (root / ROSTER_SUBPATH).is_file():
            return root
    raise RoleTypesError(
        "the roles library was not found; agent-launcher is not at "
        + ", ".join(str(path) for path in tried)
    )


def load_roster(agent_launcher: Path) -> Any:
    """Import agent-launcher's roster helper, the owner of the role mapping and the index reader."""
    path = agent_launcher / ROSTER_SUBPATH
    spec = importlib.util.spec_from_file_location(f"_saga_roster@{path.parent}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib internal failure
        raise RoleTypesError(f"the roster helper at {path} could not be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- tiers


def _load_staffing() -> Any:
    """Fleet-core's staffing resolver, from the build-time bundle beside this file."""
    import bundled_fleet  # noqa: PLC0415  (the bundle loader, imported only when a role resolves)

    return bundled_fleet.load("staffing")


def _accepts(function: Callable[..., Any], name: str) -> bool:
    try:
        return name in inspect.signature(function).parameters
    except (TypeError, ValueError):  # pragma: no cover - a builtin with no signature
        return False


def resolve_with_staffing(
    role: str,
    cwd: Path,
    *,
    answer: Mapping[str, str] | None = None,
    jev_raise: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Ask the staffing resolver for *role*'s tier, with the run's recorded inputs.

    ``staffing.resolve_role`` applies the one precedence order (operator answer, repository
    overlay under *cwd*, recorded Jev raise, work-shape default) and refuses a raise that is not
    exactly one step above its base. This function hands it the inputs and interprets none of
    them. A resolver that predates those inputs (issue #93) cannot apply them: a recorded raise is
    then refused by name rather than dropped, and an operator answer, which outranks every other
    layer, is returned as the operator gave it.
    """
    staffing = _load_staffing()
    kwargs: dict[str, Any] = {"root": cwd, "require_lens": False}
    if jev_raise is not None:
        if not _accepts(staffing.resolve_role, "jev_raise"):
            raise RoleTypesError(
                "the run records a Jev raise and this build's staffing resolver cannot apply one"
            )
        kwargs["jev_raise"] = jev_raise
    operator_answer: dict[str, str] | None = None
    if answer is not None:
        if _accepts(staffing.resolve_role, "answer"):
            kwargs["answer"] = answer
        else:
            operator_answer = {"model": str(answer["model"]), "effort": str(answer["effort"])}
    decision = staffing.resolve_role(role, **kwargs).as_dict()
    if not isinstance(decision, Mapping):
        raise RoleTypesError("the resolver did not answer with a mapping")
    if operator_answer is not None:
        decision = {**decision, **operator_answer, "source": "operator"}
    return decision


def staffing_rows(record: Any) -> tuple[Mapping[str, Any], bool]:
    """The record's staffing plan (``{}`` while unset), and whether the operator wrote all of it."""
    entry = record.run_configuration.get("staffing_models_and_efforts")
    value = entry.get("value") if isinstance(entry, Mapping) else entry
    whole_map_is_operator = isinstance(entry, Mapping) and entry.get("source") == "operator"
    return (value if isinstance(value, Mapping) else {}), whole_map_is_operator


def tier_for(
    role: str, row: Any, cwd: Path, resolver: Resolver, *, operator: bool = False
) -> dict[str, str]:
    """The role's vendor, model and effort, as the staffing resolver answers it for this run.

    This function decides no precedence. It gathers the run's recorded inputs for the role and
    hands them to the resolver: the row as the operator's answer when the operator wrote it (the
    whole map from a ``staffing_overrides`` answer, or a row marked ``operator_override``), and
    the row's ``jev_raise`` when one is recorded. A row admission filled from the resolver is
    answered again by the resolver, so the overlay and a recorded raise apply exactly as they do
    everywhere else.
    """
    row = row if isinstance(row, Mapping) else {}
    by_operator = operator or row.get("operator_override") is True
    answer = (
        {"model": str(row["model"]), "effort": str(row["effort"])}
        if by_operator and row.get("model") and row.get("effort")
        else None
    )
    raise_ = row.get("jev_raise")
    jev_raise = raise_ if isinstance(raise_, Mapping) and raise_ else None
    decision = resolver(role, cwd, answer=answer, jev_raise=jev_raise)
    vendor = str(row.get("vendor") or "") if answer is not None else ""
    return {
        "vendor": vendor or str(decision.get("vendor") or ""),
        "model": str(decision.get("model") or ""),
        "effort": str(decision.get("effort") or ""),
        "source": str(decision.get("source") or "resolver"),
    }


# --------------------------------------------------------------------------- the answer


def strip_frontmatter(text: str) -> str:
    """The role file's body: everything after a leading ``---`` YAML block."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    return text[end + len("\n---\n") :].lstrip("\n")


def fingerprint(types: Sequence[Mapping[str, Any]]) -> str:
    """One hash of every type's name, tier and prompt, so a caller re-declares only on a change."""
    material = json.dumps(
        [[t["role"], t["model"], t["effort"], t["prompt"]] for t in types], sort_keys=True
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _empty(active: bool, issue: int | None, **extra: Any) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "schema": SCHEMA,
        "active": active,
        "issue": issue,
        "types": [],
        "skipped": [],
        "fingerprint": fingerprint([]),
    }
    answer.update(extra)
    return answer


def describe(readable_role: str, role: str, issue: int, model: str, effort: str) -> str:
    return (
        f"Saga run role {readable_role} (staffing role {role}) for issue #{issue}, staffed at "
        f"{model}/{effort}. Dispatch the run's {role} work to it when the unit's resolved tier is "
        f"{model}/{effort}; it returns its result as its final message."
    )


def role_agent_types(
    cwd: Path,
    *,
    store_root: Path | None = None,
    agent_launcher: Path | None = None,
    roles_dir: Path | None = None,
    resolver: Resolver = resolve_with_staffing,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The answer for *cwd*. Never raises: every failure is a named ``error``."""
    cwd = Path(cwd)
    announcement = next_step_context.next_step_for(cwd, store_root=store_root)
    if announcement is None:
        return _empty(False, None)
    issue = int(announcement["issue"])

    try:
        resolved_store = (
            Path(store_root) if store_root is not None else run_record.resolve_store_root(cwd)
        )
        record = run_record.load(resolved_store, issue, warn=None)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        return _empty(True, issue, error=f"the run record could not be read: {exc}")
    if record is None:  # removed between the two reads
        return _empty(False, None)

    try:
        launcher_root = locate_agent_launcher(agent_launcher, env=env)
        roster = load_roster(launcher_root)
        library = Path(roles_dir) if roles_dir is not None else launcher_root / ROLES_SUBPATH
        index = roster.load_roles_index(library / "index.json")
    except Exception as exc:  # noqa: BLE001
        return _empty(True, issue, error=str(exc))

    rows, operator_map = staffing_rows(record)
    mapping: Mapping[str, str] = roster.STAFFING_ROLE_TO_ROLE_ID
    readable = {
        str(row.get("role_id")): str(row.get("role") or row.get("role_id"))
        for row in index.get("roles", [])
        if isinstance(row, Mapping)
    }

    types: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for role in sorted(rows):
        if role not in mapping:
            skipped.append({"role": str(role), "reason": "no role prompt in the roles library"})
    for role in sorted(mapping):
        if role == LENS_ROLE:
            if role in rows:
                skipped.append(
                    {"role": role, "reason": "its prompt is sliced per lens; one type cannot carry it"}
                )
            continue
        role_id = mapping[role]
        try:
            tier = tier_for(role, rows.get(role), cwd, resolver, operator=operator_map)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"role": role, "reason": f"its tier could not be resolved: {exc}"})
            continue
        if tier["vendor"] != VENDOR:
            skipped.append({"role": role, "reason": f"staffed on {tier['vendor'] or 'no vendor'}"})
            continue
        if not tier["model"] or not tier["effort"]:
            skipped.append({"role": role, "reason": "its staffing names no model or effort"})
            continue
        try:
            prompt_path = library / roster.role_file_name(index, role_id)
            body = strip_frontmatter(prompt_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            skipped.append({"role": role, "reason": f"its role prompt could not be read: {exc}"})
            continue
        name = readable.get(role_id, role_id)
        types.append(
            {
                "role": role,
                "role_id": role_id,
                "readable_role": name,
                "prompt_path": str(prompt_path),
                "prompt": HOSTING_PREAMBLE + body,
                "model": tier["model"],
                "effort": tier["effort"],
                "source": tier["source"],
                "description": describe(name, role, issue, tier["model"], tier["effort"]),
            }
        )

    answer = _empty(True, issue)
    answer.update({"types": types, "skipped": skipped, "fingerprint": fingerprint(types)})
    return answer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="role_agent_types.py",
        description="Print what each staffed role of this checkout's active saga run runs as.",
    )
    parser.add_argument("--cwd", type=Path, default=None, help="the checkout (default: here)")
    parser.add_argument("--store-root", type=Path, default=None, help="the run record store")
    parser.add_argument(
        "--agent-launcher", type=Path, default=None, help="agent-launcher's package root"
    )
    parser.add_argument("--roles-dir", type=Path, default=None, help="the roles library folder")
    parser.add_argument("--json", action="store_true", help="print JSON (the only format)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        answer = role_agent_types(
            args.cwd or Path.cwd(),
            store_root=args.store_root,
            agent_launcher=args.agent_launcher,
            roles_dir=args.roles_dir,
        )
    except Exception as exc:  # noqa: BLE001 - the caller is a hook; never a traceback
        answer = _empty(False, None, error=f"role_agent_types failed: {exc}")
    print(json.dumps(answer, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
