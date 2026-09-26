"""Tests: PyPI package layer stays in lockstep with the single-file source.

The canonical implementation is `xthread-agent.py` (hyphenated, curl-and-run).
The publishable wheel carries a byte-identical copy as `xthread_agent/__init__.py`.
If this test fails, run `python3 scripts/sync_package.py` and re-commit.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestPackageSync(unittest.TestCase):
    def test_package_init_is_byte_identical_to_source_of_truth(self):
        src = (ROOT / "xthread-agent.py").read_bytes()
        dst = (ROOT / "xthread_agent" / "__init__.py").read_bytes()
        self.assertEqual(src, dst,
                         "xthread_agent/__init__.py has drifted from xthread-agent.py — "
                         "run scripts/sync_package.py")

    def test_dunder_main_entry_exists(self):
        main_py = (ROOT / "xthread_agent" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("main()", main_py)
        self.assertIn("__main__", main_py)

    def test_pyproject_version_tracks_tool_version(self):
        tool = (ROOT / "xthread-agent.py").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        import re
        m_tool = re.search(r'^__version__\s*=\s*"([^"]+)"', tool, re.M)
        m_toml = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
        self.assertIsNotNone(m_tool)
        self.assertIsNotNone(m_toml)
        self.assertEqual(m_tool.group(1), m_toml.group(1),
                         "pyproject.toml version != xthread-agent.py __version__")


if __name__ == "__main__":
    unittest.main()
