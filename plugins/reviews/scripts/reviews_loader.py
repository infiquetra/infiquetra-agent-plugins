"""Load reviews siblings without occupying the bare names Saga tests import.

Saga and reviews both ship modules such as ``review_records``. A combined pytest
process imports both trees. Registering the reviews copy as ``sys.modules['review_records']``
makes Saga call a module that no longer has ``record_run``. Every reviews sibling is
therefore stored only as ``infiquetra_reviews.<name>``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PREFIX = "infiquetra_reviews"


def load(name: str):
    """Return the reviews sibling ``name`` without binding the bare module name."""
    key = f"{_PREFIX}.{name}"
    loaded = sys.modules.get(key)
    if loaded is not None:
        return loaded
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module
