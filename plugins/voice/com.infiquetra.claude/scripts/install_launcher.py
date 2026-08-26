"""Write a stable ``voice`` launcher, so an operator keybinding can survive updates.

Claude installs a plugin under a *versioned* directory --
``~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`` -- and a version
bump creates a new directory rather than reusing the old one. There is no
``current`` or ``latest`` symlink. So no path inside an installed package is
stable, and a Herdr keybinding written against one silently stops working at the
next release: the key still exists, the command still parses, and nothing runs.

This writes a small launcher to a directory on ``PATH`` that resolves the
current install at *invocation* time, from Claude's own installed-plugin
registry. The registry is the right source because Claude maintains it: it
rewrites ``installPath`` on every install and update, so the launcher follows a
version bump with no reconfiguration anywhere.

The emitted launcher is deliberately self-contained. It cannot import anything
from the package, because finding the package is the job it exists to do.

**This never runs on its own.** It is an explicit operator command, and it
writes exactly one file, only inside the operator's own executable directory,
only after saying what it is about to do. Voice writes no Herdr configuration
here or anywhere else (R15): what the operator does with the resulting command
is theirs to decide, and the keybinding stays a manual step.

This module lives in the Claude client extension rather than the portable core
because reading Claude's plugin registry is Claude client knowledge. The
portable package neither knows nor needs to know how a vendor lays out an
install.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path


#: Claude's installed-plugin registry. Stable across versions, and rewritten by
#: Claude on every install and update -- which is exactly the property the
#: versioned install directory lacks.
REGISTRY = Path("~/.claude/plugins/installed_plugins.json")

#: The plugin's registry key, ``<plugin>@<marketplace>``.
PLUGIN_KEY = "voice@infiquetra-agent-plugins"

#: Where the launcher goes. First on this operator's ``PATH`` and already the
#: home of ``herdr``, ``claude``, and ``agent``, so it is the established
#: convention rather than a new one invented here.
DEFAULT_LAUNCHER = Path("~/.local/bin/voice")

#: The launcher body. It resolves the newest install by ``lastUpdated`` and
#: execs the package CLI, forwarding every argument. Failure is reported by
#: name on stderr: a stop key that silently does nothing is the defect this
#: whole module exists to prevent.
LAUNCHER_BODY = '''#!/usr/bin/env python3
"""Resolve the installed voice package and run its CLI. Generated file.

Regenerate with:
    python3 <install>/com.infiquetra.claude/scripts/install_launcher.py

Resolution happens on every invocation, so a Claude plugin update that moves
the package to a new version directory needs no change here.
"""
import json
import os
import sys
from pathlib import Path

REGISTRY = Path({registry!r}).expanduser()
PLUGIN_KEY = {plugin_key!r}


def main() -> int:
    if not REGISTRY.is_file():
        print(f"voice: no Claude plugin registry at {{REGISTRY}}", file=sys.stderr)
        return 1
    try:
        entries = json.loads(REGISTRY.read_text(encoding="utf-8"))
        entries = entries["plugins"][PLUGIN_KEY]
    except (OSError, ValueError, KeyError):
        print(
            f"voice: {{PLUGIN_KEY}} is not installed; "
            "run `claude plugin install " + PLUGIN_KEY + "`",
            file=sys.stderr,
        )
        return 1
    if not entries:
        print(f"voice: {{PLUGIN_KEY}} has no install recorded", file=sys.stderr)
        return 1
    newest = sorted(entries, key=lambda e: e.get("lastUpdated", ""))[-1]
    cli = Path(newest["installPath"]) / "scripts" / "voice_cli.py"
    if not cli.is_file():
        print(f"voice: the recorded install has no CLI at {{cli}}", file=sys.stderr)
        return 1
    os.execv(sys.executable, [sys.executable, str(cli), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
'''


def render_launcher() -> str:
    """The launcher text, with this module's registry contract baked in."""
    return LAUNCHER_BODY.format(registry=str(REGISTRY), plugin_key=PLUGIN_KEY)


def install(destination: Path | str | None = None, *, force: bool = False) -> Path:
    """Write the launcher and mark it executable. Returns where it landed.

    Refuses to overwrite a file this module did not generate unless ``force``
    is given: something else called ``voice`` on the operator's ``PATH`` is
    theirs, and clobbering it silently would be exactly the kind of unrequested
    write this package does not do.
    """
    path = Path(destination).expanduser() if destination else DEFAULT_LAUNCHER.expanduser()
    body = render_launcher()
    if path.exists() and not force:
        existing = path.read_text(encoding="utf-8", errors="replace")
        if "Generated file." not in existing:
            raise SystemExit(
                f"voice: {path} exists and was not generated by this command; "
                "inspect it, then pass --force to replace it"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install_launcher",
        description=(
            "Write a stable `voice` launcher onto PATH so a Herdr keybinding "
            "survives Claude plugin version updates. Writes one file; never "
            "touches Herdr configuration."
        ),
    )
    parser.add_argument(
        "--destination",
        default=None,
        help=f"where to write the launcher (default: {DEFAULT_LAUNCHER})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace a file this command did not generate",
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="print the launcher instead of writing it",
    )
    arguments = parser.parse_args(argv)

    if arguments.print_only:
        sys.stdout.write(render_launcher())
        return 0

    path = install(arguments.destination, force=arguments.force)
    print(f"voice: launcher written to {path}")
    directory = str(path.parent)
    on_path = directory in os.environ.get("PATH", "").split(os.pathsep)
    if on_path:
        print(f"voice: {directory} is on PATH — `voice stop` is runnable now")
    else:
        print(
            f"voice: {directory} is NOT on PATH; add it, or the keybinding "
            "will parse and do nothing"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
