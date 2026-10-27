"""scripts/dependency_audit.py (#369): which audit findings fail CI, and the dated ignore list. No network: the
reports below have the shape of `npm audit --omit=dev --json` (npm 11) and `pip-audit --format json` (2.10)."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import dependency_audit as audit  # noqa: E402

TODAY = "2026-10-21"


def npm_report(*advisories: tuple[str, str, str]) -> dict:
    """advisories: (package, GHSA id, severity). A dependent package points at it by name, as npm reports it."""
    vulns = {}
    for package, ghsa, severity in advisories:
        vulns[package] = {"name": package, "severity": severity, "isDirect": False,
                          "via": [{"source": 1100000, "name": package, "title": f"Issue in {package}",
                                   "url": f"https://github.com/advisories/{ghsa}", "severity": severity,
                                   "range": "<9.9.9"}], "effects": ["react-dom"], "fixAvailable": True}
        vulns["react-dom"] = {"name": "react-dom", "severity": severity, "via": [package], "effects": []}
    return {"auditReportVersion": 2, "vulnerabilities": vulns,
            "metadata": {"vulnerabilities": {}, "dependencies": {"prod": 9, "dev": 82, "total": 90}}}


def pip_report(*vulns: tuple[str, str, list[str]]) -> dict:
    deps = [{"name": "fastapi", "version": "0.1", "vulns": []}]
    for package, vid, aliases in vulns:
        deps.append({"name": package, "version": "1.0", "vulns": [
            {"id": vid, "fix_versions": ["1.1"], "aliases": aliases, "description": "A described problem."}]})
    return {"dependencies": deps, "fixes": []}


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dependency-audit-"))
        self.ignore = self.tmp / ".audit-ignore.json"
        self.write_ignores([])

    def tearDown(self):
        for path in self.tmp.iterdir():
            path.unlink()
        self.tmp.rmdir()

    def write_ignores(self, entries: list[dict]) -> None:
        self.ignore.write_text(json.dumps({"schema": "aware-care-audit-ignore/1", "ignores": entries}))

    def run_audit(self, kind: str, report) -> tuple[int, str]:
        path = self.tmp / "report.json"
        path.write_text(report if isinstance(report, str) else json.dumps(report))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = audit.main([kind, str(path), "--ignore-file", str(self.ignore), "--today", TODAY])
        return code, out.getvalue() + err.getvalue()

    def entry(self, **overrides) -> dict:
        return {"id": "GHSA-aaaa-bbbb-cccc", "ecosystem": "npm", "package": "left-pad",
                "reason": "Not reachable: only used at build time.", "expires": "2026-11-30", **overrides}

    def test_clean_reports_pass(self):
        self.assertEqual(self.run_audit("npm", npm_report())[0], 0)
        self.assertEqual(self.run_audit("python", pip_report())[0], 0)

    def test_npm_high_and_critical_fail_moderate_does_not(self):
        for severity, expected in (("critical", 1), ("high", 1), ("moderate", 0), ("low", 0)):
            code, out = self.run_audit("npm", npm_report(("left-pad", "GHSA-aaaa-bbbb-cccc", severity)))
            self.assertEqual(code, expected, (severity, out))
            self.assertIn("GHSA-aaaa-bbbb-cccc", out)

    def test_every_python_vulnerability_fails(self):
        code, out = self.run_audit("python", pip_report(("certifi", "PYSEC-2026-4320", ["GHSA-6q48-6c7w-9gw2"])))
        self.assertEqual(code, 1)
        self.assertIn("FAIL: certifi PYSEC-2026-4320", out)

    def test_a_dated_ignore_entry_accepts_the_finding(self):
        self.write_ignores([self.entry()])
        code, out = self.run_audit("npm", npm_report(("left-pad", "GHSA-aaaa-bbbb-cccc", "critical")))
        self.assertEqual(code, 0, out)
        self.assertIn("ignored until 2026-11-30: Not reachable", out)

    def test_an_alias_matches_a_python_finding(self):
        self.write_ignores([self.entry(id="GHSA-6q48-6c7w-9gw2", ecosystem="pypi", package="certifi")])
        code, out = self.run_audit("python", pip_report(("certifi", "PYSEC-2026-4320", ["GHSA-6q48-6c7w-9gw2"])))
        self.assertEqual(code, 0, out)

    def test_an_entry_for_another_package_or_ecosystem_does_not_match(self):
        report = npm_report(("left-pad", "GHSA-aaaa-bbbb-cccc", "high"))
        for other in (self.entry(package="right-pad"), self.entry(ecosystem="pypi")):
            self.write_ignores([other])
            self.assertEqual(self.run_audit("npm", report)[0], 1)

    def test_an_expired_entry_fails_even_without_findings(self):
        self.write_ignores([self.entry(expires="2026-10-20")])
        code, out = self.run_audit("npm", npm_report())
        self.assertEqual(code, 1)
        self.assertIn("expired on 2026-10-20", out)

    def test_an_entry_needs_a_reason_and_a_valid_date(self):
        for broken in (self.entry(reason=""), self.entry(expires="soon"), {"id": "GHSA-aaaa-bbbb-cccc"}):
            self.write_ignores([broken])
            self.assertEqual(self.run_audit("npm", npm_report())[0], 1, broken)

    def test_a_failed_or_missing_audit_is_not_a_pass(self):
        offline = {"error": {"code": "ENOTFOUND", "summary": "request to https://registry.npmjs.org failed"}}
        self.assertEqual(self.run_audit("npm", offline)[0], 1)
        self.assertEqual(self.run_audit("npm", "")[0], 1)
        self.assertEqual(self.run_audit("python", "")[0], 1)
        self.assertEqual(self.run_audit("python", {"dependencies": [{"name": "x", "version": "1",
                                                                       "skip_reason": "not on PyPI"}]})[0], 1)
        with contextlib.redirect_stderr(io.StringIO()):
            code = audit.main(["python", str(self.tmp / "absent.json"), "--ignore-file", str(self.ignore)])
        self.assertEqual(code, 1)

    def test_the_repository_ignore_list_is_valid(self):
        entries = audit.load_ignores(ROOT / ".audit-ignore.json", audit.date.fromisoformat(TODAY))
        self.assertIsInstance(entries, list)


if __name__ == "__main__":
    unittest.main()
