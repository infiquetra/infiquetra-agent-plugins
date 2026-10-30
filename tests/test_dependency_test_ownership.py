"""Guard the stdlib/provisioned ownership boundary without importing YAML here."""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Old identities remain explicit so moving a case cannot silently drop it.
MOVED_CASES = (
    ("tests/test_mission_control_rule_audit.py", "TemplateSyncAuditTests",
     "test_template_sync_check_passes_when_templates_present",
     "plugins/mission-control/tests/test_template_sync_audit.py", "TemplateSyncAuditTests"),
    ("tests/test_mission_control_rule_audit.py", "TemplateSyncAuditTests",
     "test_template_sync_fails_on_drift",
     "plugins/mission-control/tests/test_template_sync_audit.py", "TemplateSyncAuditTests"),
    ("tests/test_mission_control_readme.py", "PortableReadmeTests",
     "test_every_fenced_bash_command_is_runnable_from_the_repository_root",
     "plugins/mission-control/tests/test_readme_commands.py", "ProvisionedReadmeTests"),
    ("tests/test_sync_marketplace.py", "StageMusePluginTests",
     "test_a_staged_saga_still_reports_the_saga_version",
     "plugins/saga/tests/test_staged_saga_version.py", "ProvisionedStageMusePluginTests"),
)


def cases(relative: str) -> set[tuple[str, str]]:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    return {(cls.name, method.name) for cls in tree.body if isinstance(cls, ast.ClassDef)
            for method in cls.body if isinstance(method, ast.FunctionDef) and method.name.startswith("test_")}


class DependencyOwnershipTests(unittest.TestCase):
    def test_remaining_root_modules_import_without_site_packages(self):
        program = '''import importlib, importlib.util, json, sys, unittest
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'tests'))
assert importlib.util.find_spec('yaml') is None
counts = {}
for name in ('test_mission_control_rule_audit', 'test_mission_control_readme', 'test_sync_marketplace'):
    module = importlib.import_module(name)
    counts[name] = unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases()
assert counts['test_mission_control_rule_audit'] == 39, counts
assert 'yaml' not in sys.modules
print(json.dumps(counts))
'''
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", program, str(ROOT)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        counts = json.loads(completed.stdout)
        self.assertEqual(counts["test_mission_control_rule_audit"], 39)
        self.assertGreater(counts["test_mission_control_readme"], 0)
        self.assertGreater(counts["test_sync_marketplace"], 0)

    def test_transferred_cases_have_one_owner_inside_the_existing_plugin_glob(self):
        expected = {}
        plugin_dirs = {p for p in ROOT.glob("plugins/*/tests") if p.is_dir()}
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("pytest plugins/*/tests", workflow)
        for old_file, old_class, method, new_file, new_class in MOVED_CASES:
            with self.subTest(case=f"{old_class}.{method}"):
                self.assertNotIn((old_class, method), cases(old_file))
                self.assertIn((new_class, method), cases(new_file))
                self.assertIn((ROOT / new_file).parent, plugin_dirs)
                expected.setdefault(new_file, set()).add((new_class, method))
        for new_file, expected_cases in expected.items():
            self.assertEqual(cases(new_file), expected_cases)
            tree = ast.parse((ROOT / new_file).read_text(encoding="utf-8"))
            # Importing support modules is safe; inheriting root test classes
            # would collect their other tests again in pytest.
            for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
                self.assertEqual([ast.unparse(base) for base in cls.bases], ["unittest.TestCase"])


if __name__ == "__main__":
    unittest.main()
