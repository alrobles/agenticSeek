"""Tests for sources.tools.safety — unsafe command detection.

Regression test for issue #29: a missing comma caused "route" and
"--force" to concatenate into the single string "route--force", leaving
both tokens unfiltered. These tests both assert the specific tokens are
blocked and guard against future accidental string concatenation in the
unsafe-token lists.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sources.tools import safety


class TestUnsafeCommandsList(unittest.TestCase):
    """Guard the structure of the unsafe-command lists."""

    def test_route_is_independent_entry(self):
        self.assertIn("route", safety.unsafe_commands_unix)

    def test_force_flag_is_independent_entry(self):
        self.assertIn("--force", safety.unsafe_commands_unix)

    def test_route_and_force_not_concatenated(self):
        self.assertNotIn("route--force", safety.unsafe_commands_unix)

    def test_no_accidental_concatenation_unix(self):
        """Every entry should be a single short token, not two tokens
        glued together by a missing comma."""
        for entry in safety.unsafe_commands_unix:
            self.assertIsInstance(entry, str)
            self.assertTrue(entry.strip(), "empty unsafe-token entry")
            # A real entry should not contain a second "--flag" appended
            # to a command name (e.g. "route--force").
            if entry.startswith("--"):
                continue
            self.assertNotIn("--", entry,
                             f"suspicious concatenation in unsafe entry: {entry!r}")

    def test_no_accidental_concatenation_windows(self):
        for entry in safety.unsafe_commands_windows:
            self.assertIsInstance(entry, str)
            self.assertTrue(entry.strip(), "empty unsafe-token entry")


class TestIsUnsafeUnix(unittest.TestCase):
    """is_unsafe() must block route and --force on POSIX platforms."""

    def setUp(self):
        # Force the unix codepath regardless of where the test runs.
        self._patcher = patch.object(safety.sys, "platform", "linux")
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_route_command_is_blocked(self):
        self.assertTrue(safety.is_unsafe("route add default gw 10.0.0.1"))

    def test_force_flag_is_blocked(self):
        self.assertTrue(safety.is_unsafe("apt-get install --force somepkg"))

    def test_concatenated_token_is_not_a_loophole(self):
        # If somebody re-introduces the missing-comma bug, the merged
        # token "route--force" still happens to match because it
        # contains both substrings. Make the intent explicit: each
        # token must independently match.
        self.assertTrue(safety.is_unsafe("route"))
        self.assertTrue(safety.is_unsafe("--force"))

    def test_safe_command_passes(self):
        self.assertFalse(safety.is_unsafe("ls -la"))
        self.assertFalse(safety.is_unsafe("echo hello"))

    def test_is_any_unsafe_detects_route(self):
        self.assertTrue(safety.is_any_unsafe(["ls", "route add default"]))

    def test_is_any_unsafe_detects_force(self):
        self.assertTrue(safety.is_any_unsafe(["echo ok", "rm -rf --force /tmp/x"]))


if __name__ == "__main__":
    unittest.main()
