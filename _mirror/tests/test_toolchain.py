"""Prevent accidental reintroduction of automatic toolchain upgrades."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ToolchainPolicyTests(unittest.TestCase):
    def test_external_actions_use_immutable_commits(self):
        references = []
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            for reference in re.findall(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", workflow.read_text(encoding="utf-8"), re.M):
                if reference.startswith("./"):
                    continue
                references.append(reference)
                self.assertRegex(reference, r"^[\w-]+/[\w./-]+@[a-f0-9]{40}$", f"Floating action in {workflow.name}")
        self.assertTrue(references)

    def test_runtime_versions_are_exact_and_dependency_install_is_frozen(self):
        workflow = (ROOT / ".github/workflows/sync-upstream.yml").read_text(encoding="utf-8")
        for field in ("python-version", "node-version", "ruby-version", "bundler"):
            values = re.findall(rf"^\s+{field}:\s*['\"]?([^'\"\s]+)", workflow, re.M)
            self.assertTrue(values, f"Missing explicit {field}")
            for value in values:
                self.assertRegex(value, r"^\d+\.\d+\.\d+$")
        self.assertIn("BUNDLE_FROZEN: 'true'", workflow)
        self.assertIn("npm ci --prefix _mirror/styles", workflow)
        lock = (ROOT / "_mirror/dependencies/Gemfile.lock").read_text(encoding="utf-8")
        self.assertIn("x86_64-linux", lock)
        self.assertIn("jekyll (4.4.1)", lock)


if __name__ == "__main__":
    unittest.main()
