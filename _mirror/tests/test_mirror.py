import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("mirror", Path(__file__).resolve().parents[1] / "mirror.py")
mirror = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mirror)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Snapshot Test")
        self.git("config", "core.autocrlf", "false")
        self.write("_config.yml", "name: original\n")
        self.write("_posts/old.md", "original article\n")
        self.write("images/sample.bin", b"\x00\xff\x80\r\n")
        self.write("README.md", "upstream readme\n")
        self.write(".github/workflows/deploy.yml", "upstream workflow\n")
        self.commit()
        self.git("branch", "upstream")
        self.write("_mirror/config.json", json.dumps({"name": "owner"}))
        self.write("README.md", "mirror maintenance\n")
        self.write(".github/workflows/deploy.yml", "protected workflow\n")
        self.write("_config.yml", "name: owner legacy customization\n")
        self.commit()

    def git(self, *args):
        return mirror.git(self.root, *args).decode().strip()

    def write(self, name, content):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-m", "fixture")

    def change_upstream(self):
        self.git("checkout", "upstream")
        self.git("mv", "_posts/old.md", "_posts/new.md")
        self.write("_config.yml", "name: original v2\ncollections: {}\n")
        self.write("_posts/new.md", "new upstream article\n")
        self.write("README.md", "upstream readme v2\n")
        self.write(".github/workflows/deploy.yml", "incompatible upstream workflow\n")
        self.commit()
        self.git("checkout", "main")

    def test_conflicting_config_rename_and_workflow_cannot_block_snapshot(self):
        self.change_upstream()
        mirror.snapshot(self.root, "upstream")
        self.assertFalse((self.root / "_posts/old.md").exists())
        self.assertEqual((self.root / "_posts/new.md").read_text(), "new upstream article\n")
        self.assertEqual((self.root / "images/sample.bin").read_bytes(), b"\x00\xff\x80\r\n")
        self.assertEqual((self.root / ".github/workflows/deploy.yml").read_text(), "protected workflow\n")
        self.assertEqual((self.root / "README.md").read_text(), "mirror maintenance\n")
        self.assertEqual(json.loads((self.root / "_mirror/config.json").read_text())["name"], "owner")
        self.commit()
        mirror.snapshot(self.root, "upstream")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_personal_root_edits_survive_as_overrides_and_raw_snapshot_stays_exact(self):
        mirror.snapshot(self.root, "upstream")
        self.commit()
        self.write("_posts/old.md", "my personal revision\n")
        self.write("extra.md", "my new page\n")
        self.commit()
        self.change_upstream()
        mirror.snapshot(self.root, "upstream")
        mirror.prepare(self.root)
        self.assertFalse((self.root / "_posts/old.md").exists())
        self.assertEqual((self.root / "_mirror/build/_posts/old.md").read_text(), "my personal revision\n")
        self.assertEqual((self.root / "_mirror/build/extra.md").read_text(), "my new page\n")
        self.assertEqual((self.root / "_posts/new.md").read_text(), "new upstream article\n")

    def test_untracked_collision_is_not_silently_overwritten(self):
        self.change_upstream()
        self.write("_posts/new.md", "uncommitted personal file\n")
        with self.assertRaisesRegex(ValueError, "Untracked file"):
            mirror.snapshot(self.root, "upstream")
        self.assertEqual((self.root / "_posts/new.md").read_text(), "uncommitted personal file\n")

    def test_paths_cannot_escape_checkout(self):
        for name in ("../outside", "/outside", ".git/config", "C:/outside", "a/../../outside"):
            with self.assertRaises(ValueError):
                mirror.safe_path(self.root, name)

    def test_personal_deletion_is_applied_only_to_build(self):
        mirror.snapshot(self.root, "upstream")
        self.commit()
        self.git("rm", "_posts/old.md")
        self.commit()
        mirror.snapshot(self.root, "upstream")
        mirror.prepare(self.root)
        self.assertTrue((self.root / "_posts/old.md").exists())
        self.assertFalse((self.root / "_mirror/build/_posts/old.md").exists())

    def test_upstream_can_replace_a_directory_with_a_file(self):
        self.git("checkout", "upstream")
        self.git("rm", "images/sample.bin")
        self.write("images", b"replacement file\n")
        self.commit()
        self.git("checkout", "main")
        mirror.snapshot(self.root, "upstream")
        self.assertEqual((self.root / "images").read_bytes(), b"replacement file\n")

    def test_new_upstream_file_matching_mirror_ignore_rules_is_still_committed(self):
        self.write(".gitignore", "*.dat\n")
        self.commit()
        self.git("checkout", "upstream")
        self.write("new-assets/data.dat", "data required by the new upstream theme\n")
        self.commit()
        self.git("checkout", "main")
        mirror.snapshot(self.root, "upstream")
        mirror.stage(self.root)
        self.assertEqual(self.git("show", ":new-assets/data.dat"), "data required by the new upstream theme")


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.config = {"source_url": "https://tingdeliu.github.io", "url": "https://garylee1210.github.io",
                       "repository": "GaryLee1210/GaryLee1210.github.io", "content_author": "Tingde Liu", "name": "GaryLee1210"}

    def test_restructured_html_keeps_authorship_and_rewrites_only_site_repository_urls(self):
        raw = ('<html><head><meta name="google-site-verification" content="original-key"></head>'
               '<BODY class="new-theme"><p>Tingde Liu wrote this article.</p>'
               '<a href="https://tingdeliu.github.io/VLN-Papers/">paper</a>'
               '<a href="https://github.com/TingdeLiu/AgentNav">author project</a>'
               '<a href="https://github.com/TingdeLiu/Tingde.Liu.github.io/issues/new">feedback</a></BODY></html>')
        result = mirror.brand_html(raw, "VLN-Papers/index.html", self.config)
        self.assertIn('id="mirror-attribution"', result)
        self.assertIn("Tingde Liu wrote this article.", result)
        self.assertIn("https://github.com/TingdeLiu/AgentNav", result)
        self.assertIn("https://github.com/GaryLee1210/GaryLee1210.github.io/issues/new", result)
        self.assertNotIn("original-key", result)
        self.assertIn('href="https://tingdeliu.github.io/VLN-Papers/">Original', result)

    def test_invalid_build_is_rejected_before_workflow_can_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "_mirror/build/_site").mkdir(parents=True)
            mirror.write_json(root / "_mirror/config.json", self.config)
            with self.assertRaisesRegex(ValueError, "Required page"):
                mirror.finalize(root)

    def test_stylesheet_gate_and_live_revision_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            site = root / "_mirror/build/_site"
            mirror.write_json(root / "_mirror/config.json", self.config)
            mirror.write_json(root / "_mirror/state.json", {"revision": "abc123"})
            for name in mirror.REQUIRED:
                page = site / name
                page.parent.mkdir(parents=True, exist_ok=True)
                page.write_text('<html><body><main>' + 'Article text. ' * 60 + '</main></body></html>')
            with self.assertRaisesRegex(ValueError, "stylesheet missing"):
                mirror.finalize(root)
            (site / "style.css").write_text('body { color: black; }\n' * 100)
            mirror.finalize(root)
            self.assertEqual(json.loads((site / "mirror-status.json").read_text())["upstream_revision"], "abc123")


if __name__ == "__main__":
    unittest.main()
