"""Public export and offline bundle regression checks; no provider access."""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate_demo import generate
from package import package
from validate import validate


class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "demo"
        self.result = generate(self.output)

    def test_demo_is_explicit_and_uses_project_metadata(self):
        self.assertTrue(self.result["demo"])
        self.assertEqual(self.result["schema_version"], "1.1")
        self.assertIn("Synthetic demo", self.result["project_name"])
        self.assertNotIn("student_id", self.result)
        self.assertNotIn("variant", self.result)
        report = validate(self.output)
        self.assertEqual((report["calls"], report["traces"]), (36, 12))
        quality = json.loads((self.output / "quality.json").read_text())
        self.assertEqual(quality["pipeline_inference_usage"]["request_count"], 0)
        self.assertEqual(self.result["classification"]["unresolved"]["trace_count"], 1)

    def test_modified_rollup_is_rejected(self):
        self.result["summary"]["call_count"] += 1
        (self.output / "results.json").write_text(json.dumps(self.result))
        with self.assertRaises(AssertionError):
            validate(self.output)

    def test_bundle_uses_allowlist_and_preserves_source_readme(self):
        (self.output / ".env").write_text("PRIVATE=not-for-export")
        (self.output / "chat.md").write_text("Private development notes")
        source_readme = self.output / "README.md"
        before = source_readme.read_bytes()
        destination = self.root / "viewer.zip"
        package(self.output, destination)
        self.assertEqual(source_readme.read_bytes(), before)
        with zipfile.ZipFile(destination) as archive:
            names = set(archive.namelist())
            self.assertIn("output/results.json", names)
            self.assertIn("code/serve.py", names)
            self.assertFalse(any(".env" in n or "chat.md" in n for n in names))
            archive.extractall(self.root / "unpacked")
        self.assertEqual(validate(self.root / "unpacked/output")["status"], "PASS")

    def test_generation_is_reproducible(self):
        second = self.root / "again"
        generate(second)
        for path in self.output.iterdir():
            self.assertEqual(path.read_bytes(), (second / path.name).read_bytes(), path.name)


if __name__ == "__main__":
    unittest.main()
