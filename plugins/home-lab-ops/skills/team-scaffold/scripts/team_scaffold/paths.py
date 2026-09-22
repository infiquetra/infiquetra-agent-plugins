"""Where the private infrastructure checkout and the context library live.

The defaults are conventional directory names under the home directory. They
are not a path on any particular machine. Set ``HOME_LAB_ROOT`` and
``INFIQUETRA_CONTEXT_LIBRARY`` when the checkouts live somewhere else.
"""

from __future__ import annotations

import os
import pathlib


def home_lab_root() -> str:
    """Root of the private infrastructure checkout.

    ``HOME_LAB_ROOT`` overrides the default. The default is ``~/home-lab``.
    """
    return os.environ.get("HOME_LAB_ROOT", "~/home-lab")


def default_hosts_path() -> str:
    """Ansible inventory inside the infrastructure checkout."""
    return str(pathlib.Path(home_lab_root()) / "ansible" / "inventory" / "hosts.yml")


def default_context_library() -> str:
    """Root of the context-library checkout.

    ``INFIQUETRA_CONTEXT_LIBRARY`` overrides the default. The default is
    ``~/infiquetra-context-library``.
    """
    return os.environ.get("INFIQUETRA_CONTEXT_LIBRARY", "~/infiquetra-context-library")
