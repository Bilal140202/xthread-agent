"""Tests: CLI behavior (offline paths only — no network in unit tests)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "xthread-agent.py"


def run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, timeout=60)


class TestCLI(unittest.TestCase):
    def test_version(self):
        r = run("--version")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "3.1.0")
        self.assertEqual(r.stderr, "")

    def test_missing_argument_is_usage_error(self):
        r = run()
        self.assertEqual(r.returncode, 2)

    def test_invalid_input_json_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("https://example.com/status/123", "--json", "--out", tmp)
        self.assertEqual(r.returncode, 1)
        payload = json.loads(r.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "invalid_input")
        self.assertEqual(payload["error"]["code"], "E_INVALID_INPUT")

    def test_invalid_input_human_readable_on_stderr(self):
        r = run("https://example.com/status/123")
        self.assertEqual(r.returncode, 1)
        self.assertIn("error:", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_profile_url_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("https://x.com/someuser", "--json", "--out", tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("E_INVALID_INPUT", r.stdout)


if __name__ == "__main__":
    unittest.main()
