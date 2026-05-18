"""Tests for the ``ecoseek`` console entry point (issue #32).

Verifies that:

* The entry-point module is importable without pulling in heavy
  optional dependencies.
* ``ecoseek --version`` and ``ecoseek --help`` work.
* Both ``ecoseek`` and ``agenticseek`` are declared as console scripts
  in setup.py and pyproject.toml.
* The dotted target in the entry-point spec resolves to a real callable.
"""

import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sources import ecoseek_entrypoint


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class TestEntryPointFunction(unittest.TestCase):

    def test_version_flag_prints_version(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ecoseek_entrypoint.main(["--version"])
        self.assertEqual(rc, 0)
        out = buf.getvalue().strip()
        self.assertTrue(out.startswith("ecoseek "), f"unexpected: {out!r}")
        # Looks like a version string (e.g. "0.1.0" or "0.1.0.dev1").
        version_part = out.split(" ", 1)[1]
        self.assertRegex(version_part, r"^[0-9]+(\.[0-9A-Za-z_.-]+)*$")

    def test_short_version_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ecoseek_entrypoint.main(["-V"])
        self.assertEqual(rc, 0)
        self.assertIn("ecoseek", buf.getvalue())

    def test_help_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ecoseek_entrypoint.main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("ecoseek", buf.getvalue().lower())

    def test_get_version_returns_string(self):
        v = ecoseek_entrypoint.get_version()
        self.assertIsInstance(v, str)
        self.assertTrue(v)


class TestEntryPointSpecRegistration(unittest.TestCase):
    """Both ``ecoseek`` and ``agenticseek`` must be declared, and the
    targets must resolve to real callables.
    """

    def _read(self, name):
        with open(os.path.join(REPO_ROOT, name), 'r', encoding='utf-8') as f:
            return f.read()

    def test_setup_py_declares_ecoseek(self):
        content = self._read("setup.py")
        self.assertIn("ecoseek=sources.ecoseek_entrypoint:main", content)

    def test_setup_py_preserves_agenticseek(self):
        content = self._read("setup.py")
        self.assertIn("agenticseek=sources.ecoseek_entrypoint:main", content)

    def test_pyproject_declares_ecoseek(self):
        content = self._read("pyproject.toml")
        self.assertIn("ecoseek", content)
        self.assertIn("sources.ecoseek_entrypoint:main", content)

    def test_entry_point_target_resolves(self):
        """``sources.ecoseek_entrypoint:main`` must point to a callable."""
        import importlib
        module = importlib.import_module("sources.ecoseek_entrypoint")
        self.assertTrue(callable(getattr(module, "main", None)))


if __name__ == "__main__":
    unittest.main()
