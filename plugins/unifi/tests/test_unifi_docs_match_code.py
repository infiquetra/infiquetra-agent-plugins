"""Assert every UniFi documentation surface agrees with the shipped client code.

Why this file exists
--------------------
Commit ``8a14ad49`` (2026-03-17) moved the Protect client to
``/proxy/protect/integration/v1`` and deleted four capabilities along the way: camera
stream URLs, PTZ control, event listing, and NVR info. The documentation kept advertising
all four for five months, and both API reference documents drifted away from the code they
claimed to describe. Nothing failed, because nothing checked.

These assertions are that check. They read the two clients as the only trustworthy
description of current behavior and compare every documentation surface against them.

How a "capability claim" is judged
----------------------------------
Two mechanical rules, chosen so that prose which *disclaims* a removed capability passes
while prose which *advertises* one fails:

1. **Command invocations must parse.** Every ``python unifi_*_client.py <resource>
   <action> [--flags]`` line in any surface is validated against the real ``argparse``
   parser the CLI builds — resource, action, and each long flag. A line naming a removed
   capability cannot parse, wherever it appears.
2. **Capability enumerations must not name a removed group.** A fixed, named list of
   enumeration strings — the manifest description, each skill's ``description``, the slash
   command's ``description``, the README skills table, and the agent's "Skills Available"
   lines — is checked word-by-word against the removed groups for the client it describes.

A sentence such as "Not implemented: ``ptz`` control" is neither an invocation nor an
enumeration, so a removal notice is allowed to say what it removed.

Endpoint paths are read from the reference documents' Markdown tables, which is where an
endpoint is *named*; surrounding prose that mentions a superseded path is not a claim that
the client calls it.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytest.importorskip("urllib3")
pytest.importorskip("requests")

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
PLUGIN_ROOT = PACKAGE_ROOT

NETWORK_CLIENT = PLUGIN_ROOT / "skills" / "unifi-network" / "scripts" / "unifi_network_client.py"
PROTECT_CLIENT = PLUGIN_ROOT / "skills" / "unifi-protect" / "scripts" / "unifi_protect_client.py"

NETWORK_SKILL = PLUGIN_ROOT / "skills" / "unifi-network" / "SKILL.md"
PROTECT_SKILL = PLUGIN_ROOT / "skills" / "unifi-protect" / "SKILL.md"
NETWORK_REFERENCE = PLUGIN_ROOT / "skills" / "unifi-network" / "references" / "udm-api-endpoints.md"
PROTECT_REFERENCE = (
    PLUGIN_ROOT / "skills" / "unifi-protect" / "references" / "protect-api-endpoints.md"
)
README = PLUGIN_ROOT / "README.md"
COMMAND_DOC = PLUGIN_ROOT / "com.infiquetra.claude" / "commands" / "unifi.md"
AGENT_DOC = PLUGIN_ROOT / "com.infiquetra.claude" / "agents" / "unifi-network-ops.md"
CHANGELOG = PLUGIN_ROOT / "CHANGELOG.md"
MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"

DOC_SURFACES = (
    NETWORK_SKILL,
    PROTECT_SKILL,
    NETWORK_REFERENCE,
    PROTECT_REFERENCE,
    README,
    COMMAND_DOC,
    AGENT_DOC,
    CHANGELOG,
)

# The open Agent Skills specification permits exactly these frontmatter fields.
PERMITTED_FRONTMATTER_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

# Removed from the Protect client in 8a14ad49; a capability enumeration may not name them.
REMOVED_PROTECT_GROUPS = ("ptz", "events", "nvr")
REMOVED_PROTECT_ACTIONS = (("cameras", "stream-url"),)

# The counts the behavior-parity inventory must reproduce, read off the parsers.
EXPECTED_NETWORK_GROUPS = 12
EXPECTED_NETWORK_ACTIONS = 52
EXPECTED_PROTECT_GROUPS = 6
EXPECTED_PROTECT_ACTIONS = 21


# --------------------------------------------------------------------------------------
# The real parser, captured from the real module
# --------------------------------------------------------------------------------------


class _ParserCaptured(Exception):  # noqa: N818 - a sentinel, not an error surface
    """Carries the fully-built root parser out of ``main()`` before it parses anything."""

    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__("parser captured")
        self.parser = parser


def _load_client(path: Path, module_name: str) -> ModuleType:
    """Import a client by path. Importing builds no client and needs no API key."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _capture_parser(module: ModuleType) -> argparse.ArgumentParser:
    """Run ``main()`` far enough to build the parser, then steal it before it parses.

    This exercises the parser the CLI actually builds rather than a re-declaration of it,
    which is the whole point: a re-declaration would drift exactly the way the docs did.
    """
    original = argparse.ArgumentParser.parse_args

    def _steal(self: argparse.ArgumentParser, *args: Any, **kwargs: Any) -> Any:
        raise _ParserCaptured(self)

    argparse.ArgumentParser.parse_args = _steal  # type: ignore[method-assign]
    try:
        module.main()
    except _ParserCaptured as captured:
        return captured.parser
    finally:
        argparse.ArgumentParser.parse_args = original  # type: ignore[method-assign]
    raise AssertionError(f"{module.__name__}.main() never built a parser")


def _subparser_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _long_flags(parser: argparse.ArgumentParser) -> set[str]:
    flags: set[str] = set()
    for action in parser._actions:
        flags.update(opt for opt in action.option_strings if opt.startswith("--"))
    return flags


def _build_surface(path: Path, module_name: str) -> dict[str, dict[str, set[str]]]:
    """Return ``{resource: {action: {--flag, ...}}}`` from the real parser."""
    parser = _capture_parser(_load_client(path, module_name))
    global_flags = _long_flags(parser)
    surface: dict[str, dict[str, set[str]]] = {}
    for resource, resource_parser in _subparser_choices(parser).items():
        actions: dict[str, set[str]] = {}
        for action, action_parser in _subparser_choices(resource_parser).items():
            actions[action] = _long_flags(action_parser) | global_flags
        surface[resource] = actions
    return surface


NETWORK_SURFACE = _build_surface(NETWORK_CLIENT, "_unifi_network_client_under_test")
PROTECT_SURFACE = _build_surface(PROTECT_CLIENT, "_unifi_protect_client_under_test")

SURFACES_BY_SCRIPT = {
    "unifi_network_client.py": NETWORK_SURFACE,
    "unifi_protect_client.py": PROTECT_SURFACE,
}


# --------------------------------------------------------------------------------------
# Extractors
# --------------------------------------------------------------------------------------

# An invocation is `python [<dir>/]unifi_*_client.py ...` on ONE line. The `python` prefix
# keeps `pytest tests/test_unifi_network_client.py` from reading as a CLI invocation, and the
# horizontal-whitespace class keeps a match from swallowing the following line.
_INVOCATION_RE = re.compile(
    r"python[^\S\n]+(?:\S*/)?(unifi_(?:network|protect)_client\.py)((?:[^\S\n]+[^\s`|]+)*)",
)
_SLASH_RE = re.compile(r"`/unifi((?:[^\S\n]+[^\s`]+)*)`")
_TABLE_ROW_RE = re.compile(r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|")
_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):")


def _invocations(text: str) -> list[tuple[str, list[str]]]:
    """Every ``unifi_*_client.py ...`` invocation as ``(script, [tokens])``."""
    found: list[tuple[str, list[str]]] = []
    for match in _INVOCATION_RE.finditer(text):
        tokens = match.group(2).split()
        found.append((match.group(1), tokens))
    return found


def _endpoint_paths(text: str) -> list[str]:
    """Endpoint paths named in a reference document's Markdown tables."""
    return [
        match.group(2)
        for line in text.splitlines()
        if (match := _TABLE_ROW_RE.match(line)) is not None
    ]


def _frontmatter(path: Path) -> tuple[list[str], dict[str, str]]:
    """Return the frontmatter's top-level keys and its scalar values."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", f"{path}: no frontmatter fence"
    keys: list[str] = []
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = _FRONTMATTER_KEY_RE.match(line)
        if match is None:
            continue
        key = match.group(1)
        keys.append(key)
        values[key] = line.split(":", 1)[1].strip()
    return keys, values


def _normalize_path_template(path: str) -> str:
    """Collapse ``{camera_id}`` / ``{id}`` / ``{mac}`` so a doc and an f-string can match."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def _client_path_templates(client: Path) -> set[str]:
    """Every URL suffix the client builds, with its base placeholder collapsed."""
    source = client.read_text(encoding="utf-8")
    templates: set[str] = set()
    for match in re.finditer(r'url = f"\{self\.(base_v1|base_v2|base_url)\}([^"]*)"', source):
        templates.add(_normalize_path_template(match.group(2)))
    return templates


NETWORK_BASES = ("/proxy/network/api/s/{site}", "/proxy/network/v2/api/site/{site}")
PROTECT_BASES = ("/proxy/protect/integration/v1",)


def _strip_base(documented: str, bases: tuple[str, ...]) -> str | None:
    for base in bases:
        if documented.startswith(base):
            return _normalize_path_template(documented[len(base) :])
    return None


# --------------------------------------------------------------------------------------
# 1 + 2. Every command shown anywhere exists in its client's parser
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("doc", DOC_SURFACES, ids=lambda p: p.name)
def test_every_documented_invocation_exists_in_the_parser(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    # Zero invocations is a legitimate answer here: a reference document names endpoints, a
    # changelog names releases, and the slash command document uses `/unifi ...` form. That
    # the extractor works at all is asserted separately, against surfaces that must have them.
    for script, tokens in _invocations(text):
        surface = SURFACES_BY_SCRIPT[script]
        where = f"{doc.relative_to(REPO_ROOT)}: `{script} {' '.join(tokens)}`"
        positional = [t for t in tokens if not t.startswith("-")]
        if not positional:
            continue  # a bare `--help`-style mention names no capability

        resource = positional[0]
        assert resource in surface, f"{where}: resource {resource!r} is not in the parser"
        if len(positional) < 2:
            continue

        action = positional[1]
        assert action in surface[resource], (
            f"{where}: {resource!r} has no action {action!r} in the parser"
        )

        for token in tokens:
            if token.startswith("--"):
                flag = token.split("=", 1)[0]
                assert flag in surface[resource][action], (
                    f"{where}: {resource} {action} accepts no flag {flag!r}"
                )


@pytest.mark.parametrize(
    ("doc", "minimum"),
    # The portable README is target-owned and does not duplicate the command
    # catalog, so it has no invocation floor. The upstream README did.
    [(NETWORK_SKILL, 52), (PROTECT_SKILL, 21), (AGENT_DOC, 10)],
    ids=lambda v: v.name if isinstance(v, Path) else str(v),
)
def test_the_invocation_extractor_actually_finds_invocations(doc: Path, minimum: int) -> None:
    """Guard the guard: a silently-broken extractor would make every check above vacuous."""
    found = _invocations(doc.read_text(encoding="utf-8"))
    assert len(found) >= minimum, (
        f"{doc.name}: extractor found {len(found)} invocations, expected at least {minimum}"
    )


def test_the_slash_extractor_finds_no_script_invocation_in_the_command_document() -> None:
    """The command document names commands only in `/unifi ...` form; keep it that way."""
    assert not _invocations(COMMAND_DOC.read_text(encoding="utf-8"))


def test_every_slash_command_reference_exists_in_a_parser() -> None:
    """`/unifi <resource> <action>` in the command document must name a real command."""
    union: dict[str, dict[str, set[str]]] = {**NETWORK_SURFACE, **PROTECT_SURFACE}
    text = COMMAND_DOC.read_text(encoding="utf-8")
    references = _SLASH_RE.findall(text)
    assert references, "no `/unifi ...` references found — the extractor is broken"

    checked = 0
    for reference in references:
        positional = [t for t in reference.split() if not t.startswith("-")]
        if len(positional) < 2:
            continue  # the usage synopsis, not a concrete command
        resource, action = positional[0], positional[1]
        if resource in ("[network|protect]", "network", "protect"):
            continue
        assert resource in union, f"/unifi {reference.strip()}: no such resource {resource!r}"
        assert action in union[resource], (
            f"/unifi {reference.strip()}: {resource!r} has no action {action!r}"
        )
        checked += 1
    assert checked, "no concrete `/unifi` command was checked"


# --------------------------------------------------------------------------------------
# 3. Every endpoint path named in a reference document exists in its client's source
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference", "client", "bases"),
    [
        (NETWORK_REFERENCE, NETWORK_CLIENT, NETWORK_BASES),
        (PROTECT_REFERENCE, PROTECT_CLIENT, PROTECT_BASES),
    ],
    ids=["network", "protect"],
)
def test_documented_endpoints_exist_in_client_source(
    reference: Path, client: Path, bases: tuple[str, ...]
) -> None:
    documented = _endpoint_paths(reference.read_text(encoding="utf-8"))
    assert documented, f"{reference}: no endpoint table rows found — the extractor is broken"

    implemented = _client_path_templates(client)
    for path in documented:
        suffix = _strip_base(path, bases)
        assert suffix is not None, (
            f"{reference.name}: `{path}` uses no base URL the client builds ({bases})"
        )
        assert suffix in implemented, (
            f"{reference.name}: `{path}` is documented but {client.name} never builds it "
            f"(it builds {sorted(implemented)})"
        )


@pytest.mark.parametrize(
    ("reference", "client", "bases"),
    [
        (NETWORK_REFERENCE, NETWORK_CLIENT, NETWORK_BASES),
        (PROTECT_REFERENCE, PROTECT_CLIENT, PROTECT_BASES),
    ],
    ids=["network", "protect"],
)
def test_every_implemented_endpoint_is_documented(
    reference: Path, client: Path, bases: tuple[str, ...]
) -> None:
    """The under-documentation direction: an implemented path with no reference row."""
    documented = {
        suffix
        for path in _endpoint_paths(reference.read_text(encoding="utf-8"))
        if (suffix := _strip_base(path, bases)) is not None
    }
    missing = sorted(_client_path_templates(client) - documented)
    assert not missing, f"{reference.name}: {client.name} builds undocumented paths: {missing}"


# --------------------------------------------------------------------------------------
# 4-8. No capability enumeration names a removed capability
# --------------------------------------------------------------------------------------


def _enumeration_lines(path: Path, needle: str) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if needle in line]


def _protect_enumerations() -> list[tuple[str, str]]:
    """Named strings that enumerate what the Protect client can do."""
    manifest = MANIFEST.read_text(encoding="utf-8")
    manifest_description = re.search(r'"description":\s*"([^"]*)"', manifest)
    assert manifest_description is not None, "plugin.json has no description"

    _, protect_frontmatter = _frontmatter(PROTECT_SKILL)
    _, command_frontmatter = _frontmatter(COMMAND_DOC)

    enumerations = [
        ("plugin.json description", manifest_description.group(1)),
        ("unifi-protect SKILL.md description", protect_frontmatter["description"]),
        ("commands/unifi.md description", command_frontmatter["description"]),
    ]
    enumerations += [
        ("README skills table", line) for line in _enumeration_lines(README, "`unifi-protect`")
    ]
    enumerations += [
        ("agent Skills Available", line)
        for line in _enumeration_lines(AGENT_DOC, "unifi_protect_client.py`)")
    ]
    return enumerations


@pytest.mark.parametrize(
    ("label", "text"),
    _protect_enumerations(),
    ids=[label for label, _ in _protect_enumerations()],
)
def test_capability_enumerations_name_no_removed_protect_group(label: str, text: str) -> None:
    words = set(re.findall(r"[a-z][a-z\-]*", text.lower()))
    for group in REMOVED_PROTECT_GROUPS:
        assert group not in words, (
            f"{label} names {group!r}, which unifi_protect_client.py does not implement"
        )
    for _resource, action in REMOVED_PROTECT_ACTIONS:
        assert action not in words, (
            f"{label} names {action!r}, which unifi_protect_client.py does not implement"
        )


def test_removed_protect_capabilities_really_are_absent() -> None:
    """Guard the guard: if a capability comes back, these assertions must be retired."""
    for group in REMOVED_PROTECT_GROUPS:
        assert group not in PROTECT_SURFACE, (
            f"{group!r} is implemented again — update REMOVED_PROTECT_GROUPS and the docs"
        )
    for resource, action in REMOVED_PROTECT_ACTIONS:
        assert action not in PROTECT_SURFACE.get(resource, {}), (
            f"{resource} {action!r} is implemented again — update REMOVED_PROTECT_ACTIONS"
        )


# --------------------------------------------------------------------------------------
# 9. Every resource group and every action appears in its skill
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("skill", "surface", "script"),
    [
        (NETWORK_SKILL, NETWORK_SURFACE, "unifi_network_client.py"),
        (PROTECT_SKILL, PROTECT_SURFACE, "unifi_protect_client.py"),
    ],
    ids=["network", "protect"],
)
def test_skill_documents_every_group_and_action(
    skill: Path, surface: dict[str, dict[str, set[str]]], script: str
) -> None:
    shown = {
        (tokens[0], tokens[1])
        for invoked_script, tokens in _invocations(skill.read_text(encoding="utf-8"))
        if invoked_script == script and len(tokens) >= 2 and not tokens[1].startswith("-")
    }
    shown_groups = {resource for resource, _ in shown}

    missing_groups = sorted(set(surface) - shown_groups)
    assert not missing_groups, f"{skill.name} documents no command for groups: {missing_groups}"

    missing_actions = sorted(
        f"{resource} {action}"
        for resource, actions in surface.items()
        for action in actions
        if (resource, action) not in shown
    )
    assert not missing_actions, f"{skill.name} documents no command for: {missing_actions}"


def test_parser_surface_matches_the_behavior_parity_inventory() -> None:
    """The counts the port's parity check must reproduce, asserted at their source."""
    assert len(NETWORK_SURFACE) == EXPECTED_NETWORK_GROUPS
    assert sum(len(a) for a in NETWORK_SURFACE.values()) == EXPECTED_NETWORK_ACTIONS
    assert len(PROTECT_SURFACE) == EXPECTED_PROTECT_GROUPS
    assert sum(len(a) for a in PROTECT_SURFACE.values()) == EXPECTED_PROTECT_ACTIONS


# --------------------------------------------------------------------------------------
# 10. Skill frontmatter conforms to the open Agent Skills specification
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("skill", [NETWORK_SKILL, PROTECT_SKILL], ids=lambda p: p.parent.name)
def test_skill_frontmatter_carries_only_permitted_fields(skill: Path) -> None:
    keys, values = _frontmatter(skill)
    disallowed = sorted(set(keys) - PERMITTED_FRONTMATTER_FIELDS)
    assert not disallowed, (
        f"{skill.parent.name}/SKILL.md frontmatter carries disallowed field(s): {disallowed}"
    )
    assert values["name"] == skill.parent.name, (
        f"{skill.parent.name}/SKILL.md frontmatter name is {values['name']!r}, "
        f"which does not match its directory"
    )


# --------------------------------------------------------------------------------------
# The parser this file reasons about is the one the CLI really builds
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("client", "surface"),
    [(NETWORK_CLIENT, NETWORK_SURFACE), (PROTECT_CLIENT, PROTECT_SURFACE)],
    ids=["network", "protect"],
)
def test_real_subprocess_help_agrees_with_the_captured_parser(
    client: Path, surface: dict[str, dict[str, set[str]]]
) -> None:
    """One real invocation per client, so the in-process capture cannot quietly diverge.

    ``--help`` needs no API key and reaches no controller: argparse exits before the client
    is constructed, and ``--confirm`` is never passed.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, str(client), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for resource in surface:
        assert resource in result.stdout, f"{client.name} --help never lists {resource!r}"
