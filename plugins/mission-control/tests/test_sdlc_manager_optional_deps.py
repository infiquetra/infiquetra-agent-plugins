"""Tests verifying sdlc_manager.py does not require PyYAML for module import, --help,
or YAML-free subcommands (#828, U11).
"""

from __future__ import annotations

import ast
import base64
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
SDLC_MANAGER_SCRIPT = SCRIPTS_DIR / "sdlc_manager.py"

sys.path.insert(0, str(SCRIPTS_DIR))
import sdlc_manager  # noqa: E402


def _run_in_unimportable_yaml_subprocess(python_code: str) -> subprocess.CompletedProcess[str]:
    """Execute Python code in a child process where `import yaml` raises ModuleNotFoundError."""
    bootstrap = f"import sys\nsys.modules['yaml'] = None\n{python_code}"
    return subprocess.run(
        [sys.executable, "-c", bootstrap],
        capture_output=True,
        text=True,
        check=False,
    )


def test_help_exits_zero_without_yaml() -> None:
    """When yaml is unimportable, `sdlc_manager.py --help` exits 0 and prints usage."""
    code = (
        "import runpy, sys\n"
        "sys.argv = ['sdlc_manager.py', '--help']\n"
        f"runpy.run_path({str(SDLC_MANAGER_SCRIPT)!r}, run_name='__main__')\n"
    )
    result = _run_in_unimportable_yaml_subprocess(code)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Infiquetra SDLC Manager" in result.stdout
    assert "usage:" in result.stdout


@pytest.mark.parametrize(
    "subcommand",
    [
        ["flow", "--help"],
        ["board", "--help"],
        ["issue", "--help"],
        ["metrics", "--help"],
    ],
)
def test_yaml_free_subcommands_work_without_yaml(subcommand: list[str]) -> None:
    """When yaml is unimportable, YAML-free subcommand help and parsing exit 0."""
    code = (
        "import runpy, sys\n"
        f"sys.argv = ['sdlc_manager.py', {', '.join(repr(arg) for arg in subcommand)}]\n"
        f"runpy.run_path({str(SDLC_MANAGER_SCRIPT)!r}, run_name='__main__')\n"
    )
    result = _run_in_unimportable_yaml_subprocess(code)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "usage:" in result.stdout


def test_mimir_coverage_fails_with_clear_message_without_yaml() -> None:
    """When yaml is unimportable, _load_live_mimir_coverage raises RuntimeError naming PyYAML."""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import sdlc_manager\n"
        "try:\n"
        "    sdlc_manager._load_live_mimir_coverage('test-repo')\n"
        "except RuntimeError as exc:\n"
        "    assert 'PyYAML is required' in str(exc)\n"
        "    assert 'no mutation performed' in str(exc)\n"
        "    sys.exit(0)\n"
        "except Exception as exc:\n"
        "    print(f'Wrong exception: {type(exc)}: {exc}', file=sys.stderr)\n"
        "    sys.exit(2)\n"
        "sys.exit(1)\n"
    )
    result = _run_in_unimportable_yaml_subprocess(code)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"


def test_mimir_coverage_succeeds_with_pyyaml_present() -> None:
    """When PyYAML is present, _load_live_mimir_coverage parses valid YAML coverage."""
    doc_text = """repository_coverage:
  schema_version: 1
  policy_version: repository-coverage/v1
  default_disposition: quarantine
  repositories:
    - repository: infiquetra/test-repo
      state: active
      route: pilot
      events: [issues, pull_request]
"""
    encoded = base64.b64encode(doc_text.encode()).decode()
    with patch.object(sdlc_manager, "_gh", return_value=encoded):
        coverage = sdlc_manager._load_live_mimir_coverage("test-repo")
    assert coverage["repository"] == "infiquetra/test-repo"
    assert coverage["route"] == "pilot"
    assert coverage["policy_version"] == "repository-coverage/v1"


def test_no_module_scope_yaml_import_in_ast() -> None:
    """Verify via AST that sdlc_manager.py has no top-level import yaml statement."""
    tree = ast.parse(
        SDLC_MANAGER_SCRIPT.read_text(encoding="utf-8"), filename=str(SDLC_MANAGER_SCRIPT)
    )
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "yaml", f"Found top-level 'import yaml' at line {node.lineno}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "yaml", f"Found top-level 'from yaml ...' at line {node.lineno}"


def test_mutation_proof_restoring_module_scope_yaml_import_fails_help(tmp_path: Path) -> None:
    """Mutation proof: restoring module-scope `import yaml` in sdlc_manager.py fails --help."""
    original_code = SDLC_MANAGER_SCRIPT.read_text(encoding="utf-8")
    mutated_code = original_code.replace(
        "# ===========================\n# CONFIGURATION",
        "import yaml\n\n# ===========================\n# CONFIGURATION",
        1,
    )
    assert "import yaml" in mutated_code
    mutant_path = tmp_path / "sdlc_manager_mutant.py"
    mutant_path.write_text(mutated_code, encoding="utf-8")

    code = (
        "import runpy, sys\n"
        "sys.argv = ['sdlc_manager.py', '--help']\n"
        f"runpy.run_path({str(mutant_path)!r}, run_name='__main__')\n"
    )
    result = _run_in_unimportable_yaml_subprocess(code)
    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr
