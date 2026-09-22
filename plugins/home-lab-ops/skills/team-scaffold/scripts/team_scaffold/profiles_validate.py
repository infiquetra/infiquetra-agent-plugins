"""Validate an operator-authored deploy/team_profiles.yml.

team_profiles.yml is an AUTHORED artifact (like SOUL.md), not generated — its
files have heterogeneous provenance (hand-authored + PyYAML-dumped), bespoke
comments, and a deeply-nested optional schema (fallback_providers, voice config,
headless workers, …). Rather than generate it, the scaffold validates it: the
checks below encode the invariants the hermes role + orchestration depend on,
and are proven by running against all 12 live team repos (test_profiles.py).
"""

from __future__ import annotations

import pathlib
import re

import yaml

TOKEN_VAR_RE = re.compile(r"^vault_discord_bot_token_\w+$")
KNOWN_ROLES = {
    # human-facing + headless roles seen across the fleet; unknown roles warn, not fail
    "team_lead",
    "olympian_agent",
    "engineering_council",
    "software_engineering_expert",
    "testing_expert",
    "security_expert",
    "stoic_skeptic",
    "polish_expert",
    "planner",
    "readiness_reviewer",
    "fit_reviewer",
    "security_reviewer",
    "test_reviewer",
    "announcer",
    "worker",
    "reviewer",
    "validator",
    "communications_steward",
    "time_and_task_steward",
    "bookkeeping_steward",
    "wellness_steward",
    "travel_and_expenses_steward",
    "research_steward",
    "procurement_steward",
    "skeptic_reviewer",
}


def validate_data(data: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). errors == [] means valid."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict) or "hermes_team_profiles" not in data:
        return ["top-level key 'hermes_team_profiles' missing"], []
    profiles = data["hermes_team_profiles"]
    if not isinstance(profiles, list) or not profiles:
        return ["'hermes_team_profiles' must be a non-empty list"], []

    seen_names: set[str] = set()
    for i, p in enumerate(profiles):
        where = f"profiles[{i}]"
        if not isinstance(p, dict):
            errors.append(f"{where}: not a mapping")
            continue
        name = p.get("name")
        if not name:
            errors.append(f"{where}: missing 'name'")
            continue
        where = f"profile {name!r}"
        if name in seen_names:
            errors.append(f"{where}: duplicate name")
        seen_names.add(name)
        if "role" not in p:
            errors.append(f"{where}: missing 'role'")
        if "model" not in p:
            errors.append(f"{where}: missing 'model'")

        headless = p.get("headless", False)
        token_var = p.get("discord_token_var")
        is_orchestrator = p.get("role") == "team_lead" and name.endswith(
            ("-orchestrator", "orchestrator")
        )

        if token_var is not None and not TOKEN_VAR_RE.match(token_var):
            errors.append(
                f"{where}: discord_token_var {token_var!r} must match "
                "vault_discord_bot_token_<persona>"
            )
        # Invariants on who may/may not own a Discord identity:
        if headless and token_var:
            errors.append(f"{where}: headless workers must NOT carry a discord_token_var")
        if is_orchestrator and token_var:
            warnings.append(
                f"{where}: orchestrator profile carries a discord_token_var "
                "(orchestrators post as the conductor bot, not their own)"
            )
        if not headless and not is_orchestrator and not token_var:
            warnings.append(
                f"{where}: human-facing profile has no discord_token_var "
                "(intentional only if it never posts to Discord)"
            )

        if "persona" not in p and not headless:
            warnings.append(f"{where}: non-headless profile has no 'persona'")
        role = p.get("role")
        if role and role not in KNOWN_ROLES:
            warnings.append(f"{where}: unfamiliar role {role!r} (not fatal)")

    return errors, warnings


def validate_file(path: str | pathlib.Path) -> tuple[list[str], list[str]]:
    data = yaml.safe_load(pathlib.Path(path).read_text())
    return validate_data(data)
