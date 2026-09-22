#!/usr/bin/env python3
"""Build helper (run once): materialize specs/team-*.yaml for the 12 existing teams.

Imports the TEAMS dict from the preserved migration generator, enriches each
spec with profile refs (from the live team_profiles.yml fixtures) + an inventory
block (from home-lab hosts.yml), and writes specs/team-<name>.yaml. Those specs
feed the generated deploy fixture parity check.

Usage:
  python3 materialize_specs.py \
      --gen-harness "$CLAUDE_JOB_DIR/tmp/team-scaffold-src/gen_harness.py" \
      --fixtures   "$CLAUDE_JOB_DIR/tmp/live-fixtures" \
      --hosts      "${HOME_LAB_ROOT:-$HOME/home-lab}/ansible/inventory/hosts.yml"

``--hosts`` defaults to that same path. ``HOME_LAB_ROOT`` defaults to
``~/home-lab`` and is never a particular machine's checkout.
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from team_scaffold.paths import default_hosts_path

HERE = pathlib.Path(__file__).resolve().parent
SPECS_DIR = HERE.parent / "specs"


def load_teams(gen_harness_path: pathlib.Path) -> dict:
    spec = importlib.util.spec_from_file_location("_gen_harness", gen_harness_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # side effect: regenerates to /tmp (harmless)
    return mod.TEAMS


def load_profiles(fixtures: pathlib.Path, repo: str) -> list[dict]:
    f = fixtures / repo / "deploy" / "team_profiles.yml"
    if not f.exists():
        return []
    data = yaml.safe_load(f.read_text()) or {}
    refs = []
    for p in data.get("hermes_team_profiles", []):
        ref = {"name": p["name"]}
        if p.get("persona"):
            ref["persona"] = p["persona"]
        if p.get("discord_token_var"):
            ref["discord_token_var"] = p["discord_token_var"]
        if p.get("headless"):
            ref["headless"] = True
        refs.append(ref)
    return refs


def load_inventory(hosts_yml: pathlib.Path, host_key: str) -> dict | None:
    data = yaml.safe_load(hosts_yml.read_text())

    def walk(node):
        if isinstance(node, dict):
            hosts = node.get("hosts")
            if isinstance(hosts, dict) and host_key in hosts:
                return hosts[host_key] or {}
            for v in node.values():
                got = walk(v)
                if got is not None:
                    return got
        return None

    found = walk(data)
    if not found:
        return None
    keep = {k: found[k] for k in ("ansible_host", "ansible_user") if k in found}
    return keep or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-harness", required=True, type=pathlib.Path)
    ap.add_argument("--fixtures", required=True, type=pathlib.Path)
    ap.add_argument(
        "--hosts",
        default=default_hosts_path(),
        type=pathlib.Path,
        help="default ~/home-lab/ansible/inventory/hosts.yml; override with HOME_LAB_ROOT",
    )
    args = ap.parse_args()

    teams = load_teams(args.gen_harness)
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    hosts_yml = args.hosts.expanduser()

    for repo, cfg in teams.items():
        short = repo[len("team-") :]
        spec = {
            "team": {
                "name": short,
                "display": cfg["team"],
                "host_group": cfg["hosts"],
                "limit_host": cfg["limit"],
                "pin_runtime": cfg["pin"],
                "coresident": cfg.get("coresident"),
                "roles": [{"role": r, "tags": t} for r, t in cfg["roles"]],
            },
        }
        inv = load_inventory(hosts_yml, cfg["limit"])
        if inv:
            spec["inventory"] = inv
        profiles = load_profiles(args.fixtures, repo)
        if profiles:
            spec["profiles"] = profiles
        out = SPECS_DIR / f"{repo}.yaml"
        out.write_text(yaml.safe_dump(spec, sort_keys=False, default_flow_style=False))
        print(f"  wrote {out.relative_to(HERE.parent)}  ({len(profiles)} profiles)")
    print(f"materialized {len(teams)} specs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
