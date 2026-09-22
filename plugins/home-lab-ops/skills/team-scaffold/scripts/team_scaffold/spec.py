"""team-spec.yaml — the single operator-authored input for a team.

It carries exactly what the deterministic pipeline needs: the harness data
(maps 1:1 onto the migration generator's TEAMS entry), an inventory block for
the home-lab hosts.yml write-back, and a profiles list (NAMES + token vars only)
for repo skeleton stamping + vault/identity wiring.

The full per-profile RUNTIME config (model, skills, voice, fallback_providers,
…) lives in the operator-authored ``deploy/team_profiles.yml`` (like SOUL.md, it
is authored not generated — see profiles_validate.py). The spec deliberately
does NOT duplicate it.
"""

from __future__ import annotations

import dataclasses
import pathlib

import yaml

HOST_GROUPS = {"agent_vms", "mac_minis", "orchestrator_vms"}


@dataclasses.dataclass
class ProfileRef:
    name: str
    persona: str | None = None
    discord_token_var: str | None = None
    headless: bool = False


@dataclasses.dataclass
class TeamSpec:
    name: str  # short slug, e.g. "themis"; repo = team-<name>
    display: str  # human description -> play/README "team" string
    host_group: str  # agent_vms | mac_minis | orchestrator_vms
    limit_host: str  # --limit target; also the inventory host key
    roles: list[tuple[str, str]]  # ordered (role, tags) — must match harness exactly
    pin_runtime: bool = False
    coresident: str | None = None
    inventory: dict | None = None
    profiles: list[ProfileRef] = dataclasses.field(default_factory=list)

    @property
    def play(self) -> str:
        return f"{self.name}.yml"

    @property
    def repo(self) -> str:
        return f"team-{self.name}"

    def as_cfg(self) -> dict:
        """The dict harness_gen.render_harness expects (gen_harness cfg shape)."""
        return {
            "play": self.play,
            "team": self.display,
            "hosts": self.host_group,
            "limit": self.limit_host,
            "roles": self.roles,
            "pin": self.pin_runtime,
            "coresident": self.coresident,
            "inventory": self.inventory,
        }

    def validate(self) -> list[str]:
        """Return a list of human-readable problems ([] == valid)."""
        problems: list[str] = []
        if not self.name or "/" in self.name or self.name != self.name.lower():
            problems.append(f"team.name must be a lowercase slug, got {self.name!r}")
        if self.host_group not in HOST_GROUPS:
            problems.append(f"team.host_group {self.host_group!r} not in {sorted(HOST_GROUPS)}")
        if not self.roles:
            problems.append("team.roles is empty")
        role_names = [r for r, _ in self.roles]
        if "hermes" not in role_names:
            problems.append("team.roles must include the 'hermes' role")
        # ollama is a per-team dependency on Linux hosts (not macOS).
        linux = self.host_group in {"agent_vms", "orchestrator_vms"}
        if linux and "ollama" not in role_names:
            problems.append("Linux host_group requires the 'ollama' role (per-team inference dep)")
        if not linux and "ollama" in role_names:
            problems.append("macOS (mac_minis) teams must NOT include the 'ollama' role")
        if self.host_group == "orchestrator_vms" and "hermes_orchestrator" not in role_names:
            problems.append("orchestrator_vms host_group expects the 'hermes_orchestrator' role")
        return problems


def _parse_roles(raw: list) -> list[tuple[str, str]]:
    roles: list[tuple[str, str]] = []
    for item in raw or []:
        if isinstance(item, dict):
            roles.append((item["role"], item["tags"]))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            roles.append((item[0], item[1]))
        else:
            raise ValueError(f"bad role entry: {item!r} (want {{role, tags}})")
    return roles


def load_spec(path: str | pathlib.Path) -> TeamSpec:
    data = yaml.safe_load(pathlib.Path(path).read_text())
    return from_dict(data)


def from_dict(data: dict) -> TeamSpec:
    team = data["team"]
    profiles = [
        ProfileRef(
            name=p["name"],
            persona=p.get("persona"),
            discord_token_var=p.get("discord_token_var"),
            headless=p.get("headless", False),
        )
        for p in (data.get("profiles") or [])
    ]
    return TeamSpec(
        name=team["name"],
        display=team["display"],
        host_group=team["host_group"],
        limit_host=team["limit_host"],
        roles=_parse_roles(team.get("roles", [])),
        pin_runtime=team.get("pin_runtime", False),
        coresident=team.get("coresident"),
        inventory=data.get("inventory"),
        profiles=profiles,
    )
