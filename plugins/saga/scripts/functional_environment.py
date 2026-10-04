"""The repository's functional-test environment, or its waiver (issue #97, pre-review testing U2).

A repository says once, in its tracked ``.saga-profile.json``, how a change is functionally tested
before code review: which kind of environment, the command that deploys or starts the change, the
command that runs the functional suite against it, an optional teardown, and whether the
environment is private to the branch or shared. A repository where functional testing does not
apply, such as a documentation-only catalog, records a waiver with its reason instead. This module
reads, checks and writes that declaration. It runs nothing: running the commands on the combined
branch is pre-review testing U4.

The plugin never chooses the mechanism (parent ruling 2). A profile from before this change that
declared ``branch_preview: true`` with a ``branch_preview_command`` is read as an *incomplete*
declaration: the command becomes the deploy command of a private ephemeral stack, the test command
is missing, and admission asks once with those values as the default, so the operator confirms or
changes them rather than the plugin deciding.

The resolved shape, which admission records at ``admission.functional_test_environment`` and the
build loop reads, is one of:

* ``{"mode": "declared", "kind", "deploy_command", "test_command", "teardown_command", "scope",
  "source"}``
* ``{"mode": "waived", "level": "repository", "reason", "source"}``
* ``{"mode": "incomplete", ...the declared fields..., "missing": [...], "source":
  "legacy-branch-preview"}``

``source`` is ``profile`` (read from ``.saga-profile.json``) or ``operator`` (answered at
admission). House pattern, as in ``run_record.py``: no I/O at import, and every filesystem function
takes its root as an argument.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

#: The profile file, at the repository root. The same name ``admission.py`` reads.
PROFILE_FILENAME = ".saga-profile.json"

#: The profile's schema, written when admission creates a profile that did not exist.
PROFILE_SCHEMA = "repository_profile.v1"

#: The profile key for the declaration, and the admission key the resolved form is recorded under.
PROFILE_KEY = "functional_test_environment"

#: The profile key for the repository-level waiver.
WAIVER_KEY = "functional_test_waiver"

#: The two keys the declaration replaces. Read once for the migration, removed on write-back.
LEGACY_KEYS: tuple[str, ...] = ("branch_preview", "branch_preview_command")

#: The four kinds of environment, from the lifecycle's run model at infiquetra-sdlc ``e5a2be10``.
KINDS: tuple[str, ...] = ("local", "emulator", "ephemeral-stack", "shared-nonprod")

#: Whether the environment is private to the branch or shared with other runs.
SCOPES: tuple[str, ...] = ("private", "shared")

#: The optional lease block on a shared environment (issue #99): where the one-run-at-a-time lease
#: lives. ``remote`` is a git remote name or URL every deploying host can push to, ``name`` the
#: lease's name under ``refs/saga/leases/``. Both default, so the block is only needed to change them.
LEASE_FIELD = "lease"
LEASE_KEYS: tuple[str, ...] = ("remote", "name")
DEFAULT_LEASE = {"remote": "origin", "name": "shared-nonprod"}

#: A lease name is one reference path component. ``environment_lease.NAME_RE`` holds the same
#: pattern; a test keeps the two equal.
LEASE_NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,62}$"

#: The one kind whose deploy-or-start command may be omitted.
LOCAL_KIND = "local"

#: The one kind that fixes its own scope.
SHARED_KIND = "shared-nonprod"

#: The fields a declared environment carries, in the order they are written.
FIELDS: tuple[str, ...] = (
    "kind",
    "deploy_command",
    "test_command",
    "teardown_command",
    "scope",
)

MODE_DECLARED = "declared"
MODE_WAIVED = "waived"
MODE_INCOMPLETE = "incomplete"

#: The modes that answer the admission question. ``incomplete`` does not.
ANSWERED_MODES: tuple[str, ...] = (MODE_DECLARED, MODE_WAIVED)

#: A repository-level waiver: part of the repository's declaration, supplied by the operator. The
#: lifecycle's other kind, a run-level waiver for a change that carries no code, is the Planner's
#: and is not written here.
WAIVER_LEVEL = "repository"

SOURCE_PROFILE = "profile"
SOURCE_OPERATOR = "operator"
SOURCE_LEGACY = "legacy-branch-preview"


class DeclarationError(ValueError):
    """A declaration or waiver that cannot be used. Callers map it to their refusal exit code."""


def _text(value: Any) -> str | None:
    """A command as a stripped string, or ``None`` when absent or blank."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise DeclarationError(f"a command must be a string, not {type(value).__name__}")
    return value.strip() or None


def normalise_environment(block: Any) -> dict[str, Any]:
    """Check a declared environment and return its five fields. Raises :class:`DeclarationError`."""
    if not isinstance(block, dict):
        raise DeclarationError(
            f"{PROFILE_KEY} must be an object of {', '.join(FIELDS)}, or answer with "
            f'{WAIVER_KEY}: {{"reason": "..."}}'
        )
    unexpected = sorted(set(block) - set(FIELDS) - {LEASE_FIELD})
    if unexpected:
        raise DeclarationError(
            f"{PROFILE_KEY} has unexpected keys ({', '.join(unexpected)}); it carries "
            + ", ".join(FIELDS)
            + f", and optionally {LEASE_FIELD}"
        )
    kind = block.get("kind")
    if kind not in KINDS:
        raise DeclarationError(
            f"{PROFILE_KEY}.kind must be one of {', '.join(KINDS)}, not {kind!r}"
        )
    deploy = _text(block.get("deploy_command"))
    test = _text(block.get("test_command"))
    teardown = _text(block.get("teardown_command"))
    if test is None:
        raise DeclarationError(f"{PROFILE_KEY}.test_command is required for every kind")
    if deploy is None and kind != LOCAL_KIND:
        raise DeclarationError(
            f"{PROFILE_KEY}.deploy_command is required for kind {kind}; only {LOCAL_KIND} may "
            "omit it"
        )
    scope = block.get("scope")
    if kind == SHARED_KIND:
        if scope is None:
            scope = "shared"
        elif scope != "shared":
            raise DeclarationError(
                f"{PROFILE_KEY}: kind {SHARED_KIND} is always shared, so scope cannot be {scope!r}"
            )
    elif scope not in SCOPES:
        raise DeclarationError(
            f"{PROFILE_KEY}.scope must be one of {', '.join(SCOPES)} for kind {kind}, not {scope!r}"
        )
    environment: dict[str, Any] = {
        "kind": kind,
        "deploy_command": deploy,
        "test_command": test,
        "teardown_command": teardown,
        "scope": scope,
    }
    if block.get(LEASE_FIELD) is not None:
        if scope != "shared":
            raise DeclarationError(
                f"{PROFILE_KEY}.{LEASE_FIELD} applies only to a shared environment; "
                f"this one is {scope}"
            )
        environment[LEASE_FIELD] = normalise_lease(block[LEASE_FIELD])
    return environment


def normalise_lease(block: Any) -> dict[str, str]:
    """Check the optional lease block and return it with its defaults filled in."""
    if not isinstance(block, dict) or set(block) - set(LEASE_KEYS):
        raise DeclarationError(
            f"{PROFILE_KEY}.{LEASE_FIELD} must be an object of {', '.join(LEASE_KEYS)}"
        )
    remote = _text(block.get("remote")) or DEFAULT_LEASE["remote"]
    name = _text(block.get("name")) or DEFAULT_LEASE["name"]
    if not re.match(LEASE_NAME_PATTERN, name):
        raise DeclarationError(
            f"{PROFILE_KEY}.{LEASE_FIELD}.name {name!r} must be lowercase letters, digits, '.', "
            "'_' or '-', starting with a letter or digit, at most 63 characters"
        )
    return {"remote": remote, "name": name}


def lease_of(resolved: dict[str, Any] | None) -> dict[str, str] | None:
    """Where a resolved environment's lease lives, or ``None`` when it needs none (not shared)."""
    if resolved is None or resolved.get("scope") != "shared":
        return None
    declared_lease = resolved.get(LEASE_FIELD)
    if isinstance(declared_lease, dict):
        return {**DEFAULT_LEASE, **{k: str(v) for k, v in declared_lease.items() if v}}
    return dict(DEFAULT_LEASE)


def normalise_waiver(block: Any) -> dict[str, Any]:
    """Check a waiver and return ``{"reason": ...}``. A waiver without a reason is refused."""
    if not isinstance(block, dict):
        raise DeclarationError(f'{WAIVER_KEY} must be an object: {{"reason": "..."}}')
    unexpected = sorted(set(block) - {"reason"})
    if unexpected:
        raise DeclarationError(
            f"{WAIVER_KEY} has unexpected keys ({', '.join(unexpected)}); it carries reason"
        )
    reason = block.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise DeclarationError(
            f"{WAIVER_KEY} needs a reason: say why functional testing does not apply to this "
            "repository"
        )
    return {"reason": reason.strip()}


def declared(environment: dict[str, Any], source: str) -> dict[str, Any]:
    """The resolved form of a checked environment."""
    return {"mode": MODE_DECLARED, **environment, "source": source}


def waived(waiver: dict[str, Any], source: str) -> dict[str, Any]:
    """The resolved form of a checked repository-level waiver."""
    return {
        "mode": MODE_WAIVED,
        "level": WAIVER_LEVEL,
        "reason": waiver["reason"],
        "source": source,
    }


def _legacy(profile: dict[str, Any]) -> dict[str, Any] | None:
    """The migration from ``branch_preview``: an incomplete declaration, or nothing."""
    if profile.get("branch_preview") is not True:
        return None
    command = profile.get("branch_preview_command")
    deploy = command.strip() if isinstance(command, str) and command.strip() else None
    missing = ["test_command"] if deploy else ["deploy_command", "test_command"]
    return {
        "mode": MODE_INCOMPLETE,
        "kind": "ephemeral-stack",
        "deploy_command": deploy,
        "test_command": None,
        "teardown_command": None,
        "scope": "private",
        "missing": missing,
        "source": SOURCE_LEGACY,
    }


def resolve(profile: dict[str, Any]) -> dict[str, Any] | None:
    """What *profile* declares: declared, waived, incomplete (legacy), or ``None`` for nothing.

    A profile carrying both the declaration and the waiver is refused: the two are alternatives,
    and picking one would be the plugin choosing.
    """
    has_block = profile.get(PROFILE_KEY) is not None
    has_waiver = profile.get(WAIVER_KEY) is not None
    if has_block and has_waiver:
        raise DeclarationError(
            f"the profile declares both {PROFILE_KEY} and {WAIVER_KEY}; keep one"
        )
    if has_block:
        return declared(normalise_environment(profile[PROFILE_KEY]), SOURCE_PROFILE)
    if has_waiver:
        return waived(normalise_waiver(profile[WAIVER_KEY]), SOURCE_PROFILE)
    return _legacy(profile)


def from_answers(answers: dict[str, Any]) -> dict[str, Any] | None:
    """The operator's answer, resolved, or ``None`` when *answers* carries neither key.

    The answer is ``functional_test_environment`` with an environment block, or
    ``functional_test_waiver`` with ``{"reason": ...}``. A waiver may also be given nested as the
    value of ``functional_test_environment``. Raises :class:`DeclarationError`.
    """
    has_block, has_waiver = PROFILE_KEY in answers, WAIVER_KEY in answers
    if not has_block and not has_waiver:
        return None
    block = answers.get(PROFILE_KEY)
    if has_block and isinstance(block, dict) and set(block) == {WAIVER_KEY}:
        if has_waiver:
            raise DeclarationError(f"{WAIVER_KEY} is answered twice")
        return waived(normalise_waiver(block[WAIVER_KEY]), SOURCE_OPERATOR)
    if has_block and has_waiver:
        raise DeclarationError(
            f"answer {PROFILE_KEY} or {WAIVER_KEY}, not both: they are alternatives"
        )
    if has_waiver:
        return waived(normalise_waiver(answers[WAIVER_KEY]), SOURCE_OPERATOR)
    return declared(normalise_environment(block), SOURCE_OPERATOR)


def profile_entry(resolved: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The profile key and value that record *resolved*: the declaration or the waiver."""
    if resolved.get("mode") == MODE_DECLARED:
        entry = {field: resolved[field] for field in FIELDS if resolved.get(field) is not None}
        if resolved.get(LEASE_FIELD) is not None:
            entry[LEASE_FIELD] = dict(resolved[LEASE_FIELD])
        return PROFILE_KEY, entry
    if resolved.get("mode") == MODE_WAIVED:
        return WAIVER_KEY, {"reason": resolved["reason"]}
    raise DeclarationError(f"only a declared or waived environment is written, not {resolved!r}")


def write_declaration(repo_root: Path, resolved: dict[str, Any]) -> Path:
    """Write *resolved* into ``<repo_root>/.saga-profile.json`` and return the path.

    Every other key keeps its value and its place. The alternative key and both legacy keys are
    removed, so the profile never carries two answers to one question. A profile that does not
    exist yet starts as ``{"schema": "repository_profile.v1"}``. The write is atomic: a temporary
    file in the same directory, then ``os.replace``.
    """
    key, value = profile_entry(resolved)
    path = Path(repo_root) / PROFILE_FILENAME
    if path.is_file():
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DeclarationError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(profile, dict):
            raise DeclarationError(f"{path} does not hold a JSON object")
    else:
        profile = {"schema": PROFILE_SCHEMA}
    other = WAIVER_KEY if key == PROFILE_KEY else PROFILE_KEY
    for stale in (other, *LEGACY_KEYS):
        profile.pop(stale, None)
    profile[key] = value

    text = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".saga-profile.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def describe(resolved: dict[str, Any] | None) -> list[str]:
    """Human lines for *resolved*, shared by admission's summary and the build loop's dry run."""
    if resolved is None:
        return ["not declared — admission asks for it"]
    mode = resolved.get("mode")
    if mode == MODE_WAIVED:
        return [f"waived ({resolved.get('level', WAIVER_LEVEL)} level): {resolved.get('reason')}"]
    lines = [f"kind: {resolved.get('kind')} (scope: {resolved.get('scope')})"]
    deploy = resolved.get("deploy_command")
    if deploy:
        lines.append(f"deploy or start: {deploy}")
    elif resolved.get("kind") == LOCAL_KIND:
        lines.append("deploy or start: none — local")
    else:
        lines.append("deploy or start: none")
    lines.append(f"test: {resolved.get('test_command') or 'none'}")
    lines.append(f"teardown: {resolved.get('teardown_command') or 'none'}")
    lease = lease_of(resolved)
    if lease is not None:
        lines.append(
            f"lease: refs/saga/leases/{lease['name']} on {lease['remote']} (one run at a time)"
        )
    if mode == MODE_INCOMPLETE:
        lines.append(
            "incomplete: migrated from the legacy branch_preview keys; missing "
            + ", ".join(resolved.get("missing") or [])
            + " — admission asks for it"
        )
    return lines
