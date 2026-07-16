#!/usr/bin/env python3
"""Black-box regression harness for statusline.py.

statusline.py is invoked exactly the way Claude Code invokes it: as a
subprocess reading a JSON payload on stdin and writing one line to stdout.
Each test runs with HOME pointed at a fresh per-test temporary directory, so
the shared cache (~/.cache/claude-statusline) is sandboxed and runs never
touch the developer's real cache.

Later tickets (CS-001/002/003) drop their adversarial-input regression tests
onto the StatuslineTestCase base class below without reinventing this setup.

Run:  python3 -m unittest discover -s tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

# Repo root is the parent of this tests/ directory; statusline.py lives there.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUSLINE = os.path.join(REPO_ROOT, "statusline.py")


class StatuslineTestCase(unittest.TestCase):
    """Base class: sandboxed HOME + a run_statusline() helper.

    Subclasses just call self.run_statusline(payload) and assert on the
    returned CompletedProcess. Each test gets its own empty HOME, so the
    shared-rate-limits cache starts clean and is discarded on teardown.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="statusline-test-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def run_statusline(self, payload, env_overrides=None):
        """Invoke statusline.py as a subprocess.

        payload: a dict (JSON-encoded to stdin) or a raw str/bytes sent verbatim
                 (so tests can feed malformed JSON too).
        env_overrides: optional dict merged over the sandboxed environment.
        Returns the completed subprocess (text mode, stdout+stderr captured).
        """
        if isinstance(payload, (str, bytes)):
            stdin_data = payload
        else:
            stdin_data = json.dumps(payload)

        env = dict(os.environ)
        env["HOME"] = self.home
        # Isolate from any XDG cache override that could escape the sandbox.
        env.pop("XDG_CACHE_HOME", None)
        if env_overrides:
            env.update(env_overrides)

        return subprocess.run(
            [sys.executable, STATUSLINE],
            input=stdin_data,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    @property
    def cache_dir(self):
        return os.path.join(self.home, ".cache", "claude-statusline")

    def read_shared_cache(self):
        """Return the parsed shared-rate-limits.json, or None if absent."""
        path = os.path.join(self.cache_dir, "shared-rate-limits.json")
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None


class SmokeTest(StatuslineTestCase):
    """A normal payload renders a full line and exits 0."""

    def test_normal_payload_renders(self):
        payload = {
            "context_window": {
                "total_input_tokens": 60541,
                "used_percentage": 30,
            },
            "rate_limits": {
                "five_hour": {"used_percentage": 42, "resets_at": 9999999999},
                "seven_day": {"used_percentage": 12, "resets_at": 9999999999},
            },
            "model": {"display_name": "Opus 4.8 (1M context)", "id": "claude-opus-4-8"},
        }
        result = self.run_statusline(payload)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Opus 4.8 (1M context)", result.stdout)
        # 5h / 7d gauges from the rate_limits path.
        self.assertIn("5h", result.stdout)
        self.assertIn("7d", result.stdout)
        # ctx segment reflects the token count.
        self.assertIn("ctx", result.stdout)


if __name__ == "__main__":
    unittest.main()
