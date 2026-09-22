"""Both Plan test modules use the packaged reader and proof, never a parser copy."""

import runpy
from pathlib import Path

_proof = runpy.run_path(
    str(Path(__file__).resolve().parents[3] / "plugins/saga/scripts/plan_save_proof.py")
)
plan_phase_53 = _proof["plan_phase_53"]
save_blocks = _proof["save_blocks"]
save_options = _proof["save_options"]
assert_engine_binding = _proof["assert_engine_binding"]
assert_regions = _proof["assert_regions"]
assert_row = _proof["assert_row"]
assert_saved_examples = _proof["assert_saved_examples"]
SaveProbe = _proof["SaveProbe"]
