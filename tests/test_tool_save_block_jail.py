"""Tests for Tool.save_block path-traversal jail (issue #31).

The save_block helper writes LLM-controlled content to disk. Without a
realpath jail, an LLM could produce a save_path like ``../escape.txt``
or ``/etc/passwd`` and write outside the agent's work directory.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sources.tools.tools import Tools


class _TestTool(Tools):
    """Concrete subclass of the abstract Tools base for testing."""

    def __init__(self):
        super().__init__()
        self.tag = "python"

    def execute(self, blocks, safety=False):
        return ""

    def execution_failure_check(self, output):
        return False

    def interpreter_feedback(self, output):
        return ""


class TestSaveBlockJail(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.outside = tempfile.TemporaryDirectory()
        self._prev_work_dir = os.environ.get("WORK_DIR")
        os.environ["WORK_DIR"] = self.tmp.name
        self.tool = _TestTool()
        # Use realpath so macOS /var vs /private/var symlink doesn't
        # poison commonpath comparisons.
        self.tool.work_dir = os.path.realpath(self.tmp.name)

    def tearDown(self):
        if self._prev_work_dir is None:
            os.environ.pop("WORK_DIR", None)
        else:
            os.environ["WORK_DIR"] = self._prev_work_dir
        self.tmp.cleanup()
        self.outside.cleanup()

    # --- allowed writes ----------------------------------------------------

    def test_allowed_relative_write(self):
        self.tool.save_block(["hello"], "out.txt")
        written = os.path.join(self.tool.work_dir, "out.txt")
        self.assertTrue(os.path.exists(written))
        with open(written) as f:
            self.assertEqual(f.read(), "hello")

    def test_allowed_subdir_write(self):
        self.tool.save_block(["hello"], "sub/nested/out.txt")
        written = os.path.join(self.tool.work_dir, "sub", "nested", "out.txt")
        self.assertTrue(os.path.exists(written))

    def test_save_path_none_is_noop(self):
        self.tool.save_block(["x"], None)
        # No file should be created in the work dir.
        self.assertEqual(os.listdir(self.tool.work_dir), [])

    # --- rejected writes ---------------------------------------------------

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            self.tool.save_block(["pwned"], "../escape.txt")
        # No escape file written.
        parent = os.path.dirname(self.tool.work_dir)
        self.assertFalse(os.path.exists(os.path.join(parent, "escape.txt")))

    def test_deep_parent_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            self.tool.save_block(["pwned"], "../../../../tmp/escape.txt")

    def test_absolute_path_outside_is_rejected(self):
        target = os.path.join(self.outside.name, "escape.txt")
        with self.assertRaises(ValueError):
            self.tool.save_block(["pwned"], target)
        self.assertFalse(os.path.exists(target))

    def test_absolute_path_to_etc_passwd_is_rejected(self):
        # We don't actually try to write /etc/passwd — just confirm
        # the jail rejects it before any open() call.
        with self.assertRaises(ValueError):
            self.tool.save_block(["pwned"], "/etc/passwd_ecoseek_test")

    def test_empty_save_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self.tool.save_block(["x"], "")

    def test_whitespace_save_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self.tool.save_block(["x"], "   ")

    # --- symlink escape ----------------------------------------------------

    @unittest.skipIf(sys.platform.startswith("win"),
                     "symlink semantics differ on Windows")
    def test_symlink_escape_is_rejected(self):
        """A pre-existing symlink inside work_dir that points outside
        must not let save_block write through it."""
        link_path = os.path.join(self.tool.work_dir, "evil_link")
        os.symlink(self.outside.name, link_path)
        with self.assertRaises(ValueError):
            self.tool.save_block(["pwned"], "evil_link/escape.txt")
        self.assertFalse(os.path.exists(
            os.path.join(self.outside.name, "escape.txt")))

    @unittest.skipIf(sys.platform.startswith("win"),
                     "symlink semantics differ on Windows")
    def test_symlink_to_file_outside_rejected(self):
        outside_file = os.path.join(self.outside.name, "target.txt")
        with open(outside_file, "w") as f:
            f.write("original")
        link_path = os.path.join(self.tool.work_dir, "out.txt")
        os.symlink(outside_file, link_path)
        with self.assertRaises(ValueError):
            self.tool.save_block(["pwned"], "out.txt")
        with open(outside_file) as f:
            self.assertEqual(f.read(), "original")

    # --- error message hygiene --------------------------------------------

    def test_error_does_not_leak_host_path(self):
        try:
            self.tool.save_block(["x"], "../escape.txt")
        except ValueError as exc:
            msg = str(exc)
            self.assertNotIn(self.tool.work_dir, msg)
            self.assertNotIn(os.path.dirname(self.tool.work_dir), msg)
        else:
            self.fail("save_block should have raised")


if __name__ == "__main__":
    unittest.main()
