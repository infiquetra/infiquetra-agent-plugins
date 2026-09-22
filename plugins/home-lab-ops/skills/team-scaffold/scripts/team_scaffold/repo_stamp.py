"""Stamp a context-library-compliant agent-team repo skeleton.

Implements the directory contract from
``infiquetra-context-library/docs/repositories/agent-team-archetype.md``:
seeds AI-instruction files + the engineering journal from the context-library
templates, and stamps the team-specific stubs (README, constitution, identity,
orchestration, per-profile dirs). The deploy harness is written separately by
harness_gen; deploy/team_profiles.yml gets an authored-artifact template.
config.yaml / distribution.yaml are labeled DEFERRED placeholders.

Idempotent: existing files are never overwritten (so re-runs + hand edits are
safe). Returns the list of paths actually created.
"""

from __future__ import annotations

import pathlib
import shutil

from . import harness_gen
from .spec import TeamSpec

GITIGNORE = """\
# secrets never belong in the repo
*.vault_pass*
.env
.team-scaffold-state.json
.ansible/
# python
__pycache__/
*.pyc
.venv/
"""

PR_TEMPLATE = """\
## What
<!-- one-line summary -->

## Why

## Validation
- [ ] team_profiles.yml validates (`team-scaffold validate-profiles`)
- [ ] deploy dry-run clean (`ansible-playbook ... --check --diff`)
- [ ] engineering journal updated if a durable learning/decision appeared
"""

CONSTITUTION_TMPL = """\
# {display} — Constitution

Working agreement for the {name} team. Fill in as the team's purpose firms up.

## Mandate

## Operating norms

## Escalation
"""

ORCHESTRATION_README = """\
# Orchestration policy

Home for this team's orchestration-policy skill / dispatch rules.
Describe how work is assigned across this team's profiles. Empty until the team
takes on coordinated multi-profile work.
"""

SOUL_PLACEHOLDER = """\
# {persona} — SOUL

<!-- SCAFFOLD PLACEHOLDER — author this before first deploy.
     The SOUL is the agent's persona + operating instructions. For a promoted
     existing agent, pull the live SOUL instead of authoring fresh. -->

## Identity

## Mandate

## Voice & style

## Boundaries
"""

CONFIG_STUB = """\
# DEFERRED placeholder — native Hermes profile distribution is not built yet.
# Per-profile runtime config lives in deploy/team_profiles.yml today.
"""

DISTRIBUTION_STUB = """\
# DEFERRED placeholder — native `hermes profile install` packaging is deferred.
# Independent deployment is via deploy/<team>.yml (Ansible) for now.
"""

TEAM_PROFILES_TMPL = """\
---
# hermes_team_profiles for team-{name} — operator-authored (NOT generated).
# Loaded by deploy/{name}.yml vars_files. Validate with:
#   team-scaffold validate-profiles deploy/team_profiles.yml
# See references/input-contract.md for the full optional schema (provider,
# base_url, fallback_providers, skills, voice_*, headless, …).
hermes_team_profiles:
{profiles}
"""


def _profiles_block(spec: TeamSpec) -> str:
    if not spec.profiles:
        return (
            "  - name: {n}\n"
            "    persona: {n}\n"
            "    role: olympian_agent\n"
            "    model: gemini-3-flash-preview:cloud\n"
            "    reasoning_effort: medium\n"
            "    max_turns: 90\n"
            "    worker_pool: 1\n"
            "    discord_token_var: vault_discord_bot_token_{n}  # variable name only\n"
        ).format(n=spec.name)
    out = []
    for p in spec.profiles:
        out.append(f"  - name: {p.name}")
        if p.persona:
            out.append(f"    persona: {p.persona}")
        out.append("    role: olympian_agent  # EDIT")
        out.append("    model: gemini-3-flash-preview:cloud  # EDIT")
        if p.headless:
            out.append("    headless: true")
        elif p.discord_token_var:
            out.append(f"    discord_token_var: {p.discord_token_var}  # variable name only")
        out.append("")
    return "\n".join(out)


def _identity_readme(spec: TeamSpec) -> str:
    lines = [
        "# Identity references (NAMES only — never secrets)",
        "",
        "One Discord App maps 1:1 to one GitHub App per persona.",
        "",
        "| Profile | Discord token var | GitHub App |",
        "|---|---|---|",
    ]
    profiles = spec.profiles or []
    if not profiles:
        lines.append(f"| {spec.name} | `vault_discord_bot_token_{spec.name}` | `<app-slug>` |")
    for p in profiles:
        tok = f"`{p.discord_token_var}`" if p.discord_token_var else "—"
        lines.append(f"| {p.name} | {tok} | `<app-slug>` |")
    return "\n".join(lines) + "\n"


def _write_if_absent(path: pathlib.Path, content: str, created: list[str]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    created.append(str(path))


def _copy_if_absent(src: pathlib.Path, dst: pathlib.Path, created: list[str]) -> None:
    if dst.exists() or not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    created.append(str(dst))


def _symlink_if_absent(link: pathlib.Path, target: str, created: list[str]) -> None:
    """Create ``link`` as a relative symlink to sibling ``target``.

    Idempotent like ``_copy_if_absent``: skips if anything already exists at
    ``link`` (real file or symlink, even a dangling one), so re-runs and hand
    edits are preserved. Skips when ``target`` is missing, to avoid leaving a
    dangling link if the canonical file was not stamped.
    """
    if link.is_symlink() or link.exists():
        return
    if not (link.parent / target).exists():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    created.append(str(link))


def stamp(
    spec: TeamSpec, out_dir: str | pathlib.Path, context_library: str | pathlib.Path
) -> list[str]:
    root = pathlib.Path(out_dir)
    cl = pathlib.Path(context_library).expanduser()
    tmpl = cl / "templates"
    ai = tmpl / "ai-instructions"
    created: list[str] = []

    sub = {"name": spec.name, "display": spec.display}

    # AI-instruction files. AGENTS.md is the canonical real file; CLAUDE.md and
    # GEMINI.md are symlinks to it, so every agent tool reads one source of truth
    # per repo. Per-tool behavioral differences belong in the global ~/.claude,
    # ~/.gemini, and ~/.codex configs — not duplicated into each repo. copilot
    # instructions and llms.txt are distinct formats for distinct consumers, so
    # they stay as their own files.
    _copy_if_absent(ai / "AGENTS.template.md", root / "AGENTS.md", created)
    _symlink_if_absent(root / "CLAUDE.md", "AGENTS.md", created)
    _symlink_if_absent(root / "GEMINI.md", "AGENTS.md", created)
    _copy_if_absent(
        ai / "copilot-instructions.template.md",
        root / ".github" / "copilot-instructions.md",
        created,
    )
    _copy_if_absent(ai / "llms.template.txt", root / "llms.txt", created)

    # engineering journal (full seed, verbatim)
    ej_src = tmpl / "engineering-journal"
    if ej_src.is_dir():
        for f in ej_src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(ej_src)
                _copy_if_absent(f, root / "docs" / "engineering-journal" / rel, created)

    # team-specific stubs
    _write_if_absent(
        root / "README.md",
        f"# {spec.repo}\n\n{spec.display} (polyrepo).\n\n"
        "## Source of truth\n- Org standards: `infiquetra-context-library`\n"
        "- Agent instructions: [AGENTS.md](AGENTS.md)\n"
        "- Engineering journal: [docs/engineering-journal/]"
        "(docs/engineering-journal/README.md)\n",
        created,
    )
    _write_if_absent(root / ".gitignore", GITIGNORE, created)
    _write_if_absent(root / ".github" / "PULL_REQUEST_TEMPLATE.md", PR_TEMPLATE, created)
    _write_if_absent(root / "constitution.md", CONSTITUTION_TMPL.format(**sub), created)
    _write_if_absent(root / "orchestration" / "README.md", ORCHESTRATION_README, created)
    _write_if_absent(root / "identity" / "README.md", _identity_readme(spec), created)

    # per-profile dirs
    profile_names = [p.name for p in spec.profiles] or [spec.name]
    persona_for = {p.name: (p.persona or p.name) for p in spec.profiles}
    for pname in profile_names:
        pdir = root / "profiles" / pname
        _write_if_absent(
            pdir / "SOUL.md",
            SOUL_PLACEHOLDER.format(persona=persona_for.get(pname, pname)),
            created,
        )
        _write_if_absent(pdir / "skills" / ".gitkeep", "", created)
        _write_if_absent(pdir / "config.yaml", CONFIG_STUB, created)
        _write_if_absent(pdir / "distribution.yaml", DISTRIBUTION_STUB, created)

    # deploy harness + authored team_profiles template
    harness = harness_gen.render_harness(spec.as_cfg())
    for fname, content in harness.items():
        _write_if_absent(root / "deploy" / fname, content, created)
    _write_if_absent(
        root / "deploy" / "team_profiles.yml",
        TEAM_PROFILES_TMPL.format(name=spec.name, profiles=_profiles_block(spec)),
        created,
    )
    return created
