"""Drift guard (R17): the provenance-manifest producer/consumer matrix in `saga-spec.md` §13.3
stays in sync with the schema fields in `provenance_manifest.py`, in both directions.

- `test_manifest_no_orphan_field` — every schema field (including nested subrecord fields) appears
  in the matrix with a named reader (issue AC selector `manifest_no_orphan_field`).
- `test_matrix_has_no_phantom_fields` — the matrix names no field absent from the schema.

Matrix rows are read from the markdown table under "### 13.3 Producer / consumer matrix" in
`plugins/saga/references/saga-spec.md`. Field names in the first column are backtick-quoted and may
use dotted / bracket paths for nested fields (e.g. `` `output_completeness.missing_keys` ``,
`` `claims[].adjudication.decision` `` `` `claim_provenance` / `claims` ``); this guard normalizes
those to bare leaf field names before comparing against the dataclass field set, so it survives
benign matrix reformatting without caring about path notation.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SAGA_SPEC = REPO_ROOT / "plugins" / "saga" / "references" / "saga-spec.md"
SCHEMA_MODULE = REPO_ROOT / "plugins" / "saga" / "scripts" / "provenance_manifest.py"

# Dataclasses whose fields must each be traceable to a matrix row.
SCHEMA_CLASSES = [
    "Attribution",
    "Adjudication",
    "Claim",
    "OutputCompleteness",
    "ClaimProvenance",
    "Manifest",
]


def _load_provenance_manifest():
    scripts_dir = str(SCHEMA_MODULE.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("provenance_manifest", SCHEMA_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["provenance_manifest"] = module
    spec.loader.exec_module(module)
    return module


def _schema_field_names() -> set[str]:
    """All dataclass field names across the manifest schema (leaf names, not paths)."""
    module = _load_provenance_manifest()
    names: set[str] = set()
    for cls_name in SCHEMA_CLASSES:
        cls = getattr(module, cls_name)
        for f in dataclasses.fields(cls):
            names.add(f.name)
    return names


def _matrix_section() -> str:
    body = SAGA_SPEC.read_text(encoding="utf-8")
    start = body.index("### 13.3 Producer / consumer matrix")
    end = body.index("\n---\n", start)
    return body[start:end]


_ROW_RE = re.compile(r"^\|([^|]+)\|", re.MULTILINE)
_FIELD_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HEADER_CELLS = {"field"}


def _matrix_field_names() -> set[str]:
    """Leaf field names named in the matrix's first column, one row per table row.

    Cells may be dotted/bracket paths (`output_completeness.missing_keys`,
    `claims[].adjudication.decision`) or a "/"-joined alias pair (`claim_provenance` /
    `claims`) — every bare identifier token in the (backtick-stripped) cell is treated as a
    named field. The header row (`| Field | ... |`) and the separator row (`|---|...`) are
    skipped so their tokens never pollute the field set.
    """
    names: set[str] = set()
    for row in _ROW_RE.finditer(_matrix_section()):
        cell = row.group(1).strip()
        if not cell or set(cell.replace(" ", "")) <= {"-"}:
            continue
        if cell.lower() in _HEADER_CELLS:
            continue
        for tok in _FIELD_TOKEN_RE.findall(cell):
            names.add(tok)
    return names


def test_manifest_no_orphan_field() -> None:
    """R17: every schema field has a named reader in the §13.3 matrix (no orphan field)."""
    schema_fields = _schema_field_names()
    matrix_fields = _matrix_field_names()
    orphans = schema_fields - matrix_fields
    assert not orphans, (
        f"Schema field(s) {sorted(orphans)} have no row in saga-spec.md §13.3 — "
        "either add a row naming a reader, or the field is dead."
    )


def test_matrix_has_no_phantom_fields() -> None:
    """R17 (reverse direction): the matrix names no field absent from the schema (drift guard)."""
    schema_fields = _schema_field_names()
    matrix_fields = _matrix_field_names()
    phantoms = matrix_fields - schema_fields
    assert not phantoms, (
        f"saga-spec.md §13.3 names field(s) {sorted(phantoms)} that do not exist in "
        "provenance_manifest.py — matrix has drifted ahead of (or diverged from) the schema."
    )


EXTERNAL_ENGINE_WORKERS_MD = (
    REPO_ROOT
    / "plugins"
    / "team-execution"
    / "skills"
    / "team-execution"
    / "references"
    / "external-engine-workers.md"
)
WORKER_MANIFEST_MD = EXTERNAL_ENGINE_WORKERS_MD.with_name("worker-manifest.md")
