"""#368: scripts/check_all.sh and the helper under scripts/dev/.

Covers check_all's argument handling (its dry-run plan) and that no script holds a scratchpad path, a home path or a
token. Nothing here touches the network or GitHub.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CHECK_ALL = ROOT / "scripts/check_all.sh"
DEV = ROOT / "scripts/dev"

def check_all(*args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "AWARECARE_PW_LOCK"}
    return subprocess.run(["bash", str(CHECK_ALL), *args], capture_output=True, text=True, env=env, timeout=60)


class CheckAllArguments(unittest.TestCase):
    ORDER = ["Web type-check", "Design contrast", "Tooling tests", "Traceability", "Contracts",
             "Wiki lint", "Backend (mock and local)", "Browser UI"]

    def plan(self, *args: str) -> list[str]:
        r = check_all("--dry-run", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return re.findall(r"^\s+\d+\. (.+?)\s{2,}\(cd ", r.stdout, re.M)

    def test_standard_fast_and_full_plans(self):
        self.assertEqual(self.plan("--standard"), self.ORDER[:7])
        self.assertEqual(self.plan("--fast"), self.ORDER[:6])
        self.assertEqual(self.plan("--full"), self.ORDER)

    def test_changed_is_the_default(self):
        # #509: type-check, contrast, contracts, backend, then only the related browser specs (none, some or all,
        # depending on the checkout's changes, so only the fixed part is compared here). --base HEAD: CI's shallow
        # checkout has no origin/main.
        fixed = ["Web type-check", "Design contrast", "Contracts", "Backend (mock and local)"]
        self.assertEqual(self.plan("--base", "HEAD")[:4], fixed)
        self.assertEqual(self.plan("--changed", "--base", "HEAD")[:4], fixed)
        self.assertTrue(all(step.startswith("Browser UI") for step in self.plan("--changed", "--base", "HEAD")[4:]))

    def test_changed_fails_clearly_without_the_base(self):
        r = check_all("--dry-run", "--base", "no-such-ref-509")
        self.assertEqual(r.returncode, 2)
        self.assertIn("could not work out the changed files", r.stderr)

    def test_commands_match_the_documented_checks(self):
        out = check_all("--dry-run", "--full").stdout
        for command in ("(cd apps/web && npx tsc --noEmit -p .)", "python3 scripts/check_contrast.py",
                        "python3 -m unittest discover -s tests/tooling", "python3 scripts/check_traceability.py",
                        "uv run --no-project --with jsonschema==4.25.1 python scripts/check_contracts.py",
                        "python3 scripts/publish_wiki.py lint", "(cd apps/api && uv run pytest -q)",
                        "NODE_PATH=$PWD/node_modules npx playwright test"):
            self.assertIn(command, out)
        self.assertNotIn("flock", out)

    def test_playwright_lock(self):
        env = dict(os.environ, AWARECARE_PW_LOCK="/nonexistent/pw.lock")
        out = subprocess.run(["bash", str(CHECK_ALL), "--dry-run", "--full"], capture_output=True, text=True,
                             env=env).stdout
        self.assertIn('flock "$AWARECARE_PW_LOCK"', out)

    def test_bad_arguments_exit_2(self):
        for args in (["--fast", "--full"], ["--full", "--fast"], ["--changed", "--full"], ["--bogus"], ["--pre-pr"],
                     ["--repo"], ["--repo", "/nonexistent"], ["--base"]):
            with self.subTest(args=args):
                self.assertEqual(check_all(*args).returncode, 2)

    def test_a_failing_check_fails_the_run_and_the_rest_still_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, bin_dir = Path(tmp) / "repo", Path(tmp) / "bin"
            for d in ("spec", "scripts", "apps/web/node_modules", "apps/api", "tests/tooling", "bin"):
                (repo / d).mkdir(parents=True)
            bin_dir.mkdir()
            for name, code in (("check_contrast.py", 1), ("check_traceability.py", 0), ("publish_wiki.py", 0)):
                (repo / "scripts" / name).write_text(f"import sys; print('stub'); sys.exit({code})\n")
            (repo / "tests/tooling/test_ok.py").write_text("import unittest\nclass T(unittest.TestCase):\n"
                                                          "    def test(self): pass\n")
            for tool in ("npx", "uv"):
                (bin_dir / tool).write_text("#!/bin/sh\nexit 0\n")
                (bin_dir / tool).chmod(0o755)
            env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", TMPDIR=tmp)
            r = subprocess.run(["bash", str(CHECK_ALL), "--fast", "--repo", str(repo)], capture_output=True,
                               text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("| 2 | Design contrast | FAIL (1) |", r.stdout)
        for row in ("| 1 | Web type-check | PASS |", "| 3 | Tooling tests | PASS |", "| 6 | Wiki lint | PASS |"):
            self.assertIn(row, r.stdout)
        self.assertIn("1 of 6 checks FAILED", r.stdout)

    def test_help(self):
        r = check_all("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--fast", r.stdout)

    def test_never_installs_dependencies(self):
        code = [line for line in CHECK_ALL.read_text().splitlines()
                if not line.lstrip().startswith(("#", "echo "))]
        self.assertTrue(code)
        for line in code:
            self.assertNotRegex(line, r"\bnpm (ci|install|i)\b")


class ChangedUiSpecs(unittest.TestCase):
    def test_specs_are_filters_playwright_matches(self):
        # #526: Playwright 1.64 matches file arguments against the spec paths; `../../tests/ui/x.spec.ts` matched
        # nothing ("No tests found"), so check_all's related-spec step failed in every checkout.
        r = subprocess.run([sys.executable, str(ROOT / "scripts/changed_ui_specs.py"), "--", "tests/ui/perf.spec.ts"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["tests/ui/perf.spec.ts"])


class NoSecretsOrLocalPaths(unittest.TestCase):
    FILES = sorted([CHECK_ALL, *DEV.iterdir()])
    FORBIDDEN = [r"/tmp/claude-", r"scratchpad", r"/home/[a-z]", r"\bgh[pousr]_[A-Za-z0-9]{20,}",
                 r"github_pat_[A-Za-z0-9_]{20,}", r"(GH|GITHUB)_TOKEN\s*=", r"Authorization:\s*(token|Bearer)"]

    def test_scripts_hold_no_scratchpad_path_or_token(self):
        files = [p for p in self.FILES if p.is_file() and p.suffix in {".sh", ".py"}]
        self.assertGreaterEqual(len(files), 2)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for pattern in self.FORBIDDEN:
                with self.subTest(file=path.name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text))

if __name__ == "__main__":
    unittest.main()
