import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from team_wiki.cli import FROZEN_COMMANDS


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "team_wiki", *args], text=True, capture_output=True)


class CliLayerTests(unittest.TestCase):
    def test_help_lists_daily_commands_and_hides_frozen_ones(self):
        out = run("--help").stdout
        for name in ("search", "govern", "project-rules", "agent-entry", "eval", "doctor"):
            self.assertRegex(out, rf"(?m)^\s+{name}\s")
        for name in FROZEN_COMMANDS:
            self.assertNotRegex(out, rf"(?m)^\s+{name}\s", name)

    def test_frozen_commands_still_work_and_warn(self):
        result = run("budget", "--max-context", "1000")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("已冻结", result.stderr)
        self.assertIn('"applied": false', result.stdout)

    def test_daily_commands_do_not_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run("agent-entry", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("已冻结", result.stderr)

    def test_every_frozen_name_is_a_real_command(self):
        out = subprocess.run([sys.executable, "-c",
                              "import team_wiki.cli as c, argparse, sys; sys.argv=['x','--help']"],
                             capture_output=True)
        import re
        from pathlib import Path as P
        source = (P(__file__).parents[1] / "src/team_wiki/cli.py").read_text(encoding="utf-8")
        defined = set(re.findall(r'sub\.add_parser\("([^"]+)"', source))
        self.assertEqual(FROZEN_COMMANDS - defined, set())


if __name__ == "__main__":
    unittest.main()
