"""Wire a team's ansible/inventory/group_vars/all/vault.yml.

Promoted from the migration's one-shot vault_split.py (2026-05-31). Core idea is
unchanged: copy each ``vault_*: !vault |`` block VERBATIM — never decrypt — so
the encrypted blob + the single ~/.vault_pass.txt keep working. Two entry points:

* ``copy_blocks_from`` — promoted-existing agent: lift named blocks verbatim out
  of home-lab all.yml (or any source vault) into the team vault.yml.
* ``append_encrypted_block`` — brand-new team: insert a freshly produced
  ``ansible-vault encrypt_string`` block (the SKILL.md drives the encrypt; this
  just splices it in idempotently).

Both are idempotent: a var already present in the target is left untouched.
"""

from __future__ import annotations

import pathlib
import re

HEADER = (
    "---\n"
    "# Vault slice — this team's own secrets (Discord tokens etc.).\n"
    "# Blocks are stored VERBATIM (same vault password as home-lab). Polyrepo.\n"
)

_KEY_RE = re.compile(r"^[A-Za-z_][\w]*:")


def parse_blocks(text: str) -> dict[str, str]:
    """var_name -> full block text (key line through just before the next key)."""
    lines = text.splitlines(keepends=True)
    idxs = [i for i, ln in enumerate(lines) if _KEY_RE.match(ln)]
    out: dict[str, str] = {}
    for n, i in enumerate(idxs):
        end = idxs[n + 1] if n + 1 < len(idxs) else len(lines)
        name = lines[i].split(":", 1)[0]
        out[name] = "".join(lines[i:end])
    return out


def existing_vars(target: pathlib.Path) -> set[str]:
    if not target.exists():
        return set()
    return set(parse_blocks(target.read_text()))


def _write(target: pathlib.Path, blocks: dict[str, str], order: list[str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    body = HEADER + "".join(blocks[v] for v in order)
    target.write_text(body)


def copy_blocks_from(
    source_vault: pathlib.Path, target: pathlib.Path, var_names: list[str]
) -> list[str]:
    """Copy named blocks verbatim from source into target (skip already-present).

    Returns the list of vars actually added.
    """
    src_blocks = parse_blocks(source_vault.read_text())
    missing = [v for v in var_names if v not in src_blocks]
    if missing:
        raise KeyError(f"vars not found in {source_vault}: {missing}")

    have = parse_blocks(target.read_text()) if target.exists() else {}
    added = [v for v in var_names if v not in have]
    merged = dict(have)
    for v in added:
        merged[v] = src_blocks[v]
    order = list(have) + added
    _write(target, merged, order)
    return added


def append_encrypted_block(target: pathlib.Path, var_name: str, encrypted_block: str) -> bool:
    """Splice one freshly-encrypted block into target. Returns True if added.

    ``encrypted_block`` is the full ``var_name: !vault |\\n  $ANSIBLE_VAULT;...``
    text produced by ``ansible-vault encrypt_string --name <var_name>``.
    """
    have = parse_blocks(target.read_text()) if target.exists() else {}
    if var_name in have:
        return False
    block = encrypted_block if encrypted_block.endswith("\n") else encrypted_block + "\n"
    merged = dict(have)
    merged[var_name] = block
    _write(target, merged, list(have) + [var_name])
    return True
