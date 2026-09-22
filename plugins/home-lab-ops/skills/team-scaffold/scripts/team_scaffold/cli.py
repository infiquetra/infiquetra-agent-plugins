"""team-scaffold CLI — the deterministic pipeline.

The two irreducible human gates (Discord bot App create + token reveal; GitHub
App create + install) are driven by the skill's SKILL.md prose, not this CLI.
Everything here is scriptable + idempotent:

  team-scaffold validate-spec      team-spec.yaml
  team-scaffold validate-profiles  deploy/team_profiles.yml
  team-scaffold gen-harness        team-spec.yaml --out <dir>
  team-scaffold stamp              team-spec.yaml --out <dir> [--context-library PATH]
  team-scaffold vault-wire         team-spec.yaml --source <home-lab all.yml> --out <dir>
  team-scaffold register-host      team-spec.yaml [--hosts PATH] [--apply]
  team-scaffold golden             # re-derive 12 known teams vs generated fixtures
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import harness_gen, inventory_register, profiles_validate, repo_stamp
from .paths import default_context_library, default_hosts_path
from .spec import load_spec


def _cmd_validate_spec(args: argparse.Namespace) -> int:
    ts = load_spec(args.spec)
    problems = ts.validate()
    if problems:
        print(f"✗ {ts.repo}: invalid spec")
        for p in problems:
            print(f"    - {p}")
        return 1
    print(f"✓ {ts.repo}: spec valid ({len(ts.profiles)} profiles, host_group={ts.host_group})")
    return 0


def _cmd_validate_profiles(args: argparse.Namespace) -> int:
    errors, warnings = profiles_validate.validate_file(args.profiles)
    for w in warnings:
        print(f"  ! {w}")
    if errors:
        print(f"✗ {args.profiles}: {len(errors)} error(s)")
        for e in errors:
            print(f"    - {e}")
        return 1
    print(f"✓ {args.profiles}: valid ({len(warnings)} warning(s))")
    return 0


def _cmd_gen_harness(args: argparse.Namespace) -> int:
    ts = load_spec(args.spec)
    out = pathlib.Path(args.out) / "deploy"
    out.mkdir(parents=True, exist_ok=True)
    for fname, content in harness_gen.render_harness(ts.as_cfg()).items():
        (out / fname).write_text(content)
        print(f"  wrote deploy/{fname}")
    return 0


def _cmd_stamp(args: argparse.Namespace) -> int:
    ts = load_spec(args.spec)
    created = repo_stamp.stamp(ts, args.out, pathlib.Path(args.context_library).expanduser())
    print(f"stamped {len(created)} files into {args.out}")
    for c in created:
        print(f"  + {c}")
    return 0


def _cmd_vault_wire(args: argparse.Namespace) -> int:
    from . import vault_wire

    ts = load_spec(args.spec)
    target = pathlib.Path(args.out) / "ansible/inventory/group_vars/all/vault.yml"
    var_names = [p.discord_token_var for p in ts.profiles if p.discord_token_var]
    if not var_names:
        print("no discord_token_var entries in spec.profiles — nothing to wire")
        return 0
    added = vault_wire.copy_blocks_from(pathlib.Path(args.source), target, var_names)
    print(f"vault.yml: +{len(added)} block(s) ({', '.join(added) or 'none — already present'})")
    return 0


def _cmd_register_host(args: argparse.Namespace) -> int:
    ts = load_spec(args.spec)
    attrs = dict(ts.inventory or {})
    if not attrs:
        print("✗ spec has no inventory block (ansible_host/ansible_user) — cannot register")
        return 1
    changed, diff = inventory_register.register(
        args.hosts, ts.host_group, ts.limit_host, attrs, apply=args.apply
    )
    if not changed:
        print(f"· {ts.limit_host} already in inventory — no change")
        return 0
    print(diff)
    print(
        f"{'APPLIED' if args.apply else 'DRY-RUN (use --apply to write)'}: "
        f"{ts.limit_host} -> group {ts.host_group}"
    )
    return 0


def _cmd_golden(_args: argparse.Namespace) -> int:
    skill_root = pathlib.Path(__file__).resolve().parents[2]
    specs = sorted((skill_root / "specs").glob("team-*.yaml"))
    golden = skill_root / "specs" / "golden"
    fails = 0
    for sp in specs:
        ts = load_spec(sp)
        rendered = harness_gen.render_harness(ts.as_cfg())
        for fname, content in rendered.items():
            exp = (golden / ts.repo / "deploy" / fname).read_text()
            if content != exp:
                print(f"✗ {ts.repo}/deploy/{fname} DIVERGED")
                fails += 1
    if fails:
        print(f"{fails} divergence(s)")
        return 1
    print(f"✓ golden: {len(specs)} teams match generated deploy fixtures")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="team-scaffold", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate-spec")
    s.add_argument("spec")
    s.set_defaults(fn=_cmd_validate_spec)

    s = sub.add_parser("validate-profiles")
    s.add_argument("profiles")
    s.set_defaults(fn=_cmd_validate_profiles)

    s = sub.add_parser("gen-harness")
    s.add_argument("spec")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=_cmd_gen_harness)

    s = sub.add_parser("stamp")
    s.add_argument("spec")
    s.add_argument("--out", required=True)
    s.add_argument(
        "--context-library",
        default=default_context_library(),
        help="default ~/infiquetra-context-library; override with INFIQUETRA_CONTEXT_LIBRARY",
    )
    s.set_defaults(fn=_cmd_stamp)

    s = sub.add_parser("vault-wire")
    s.add_argument("spec")
    s.add_argument("--source", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=_cmd_vault_wire)

    s = sub.add_parser("register-host")
    s.add_argument("spec")
    s.add_argument(
        "--hosts",
        default=default_hosts_path(),
        help=(
            "infrastructure inventory (default: $HOME_LAB_ROOT/ansible/inventory/hosts.yml, "
            "HOME_LAB_ROOT defaults to ~/home-lab)"
        ),
    )
    s.add_argument("--apply", action="store_true")
    s.set_defaults(fn=_cmd_register_host)

    s = sub.add_parser("golden")
    s.set_defaults(fn=_cmd_golden)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
