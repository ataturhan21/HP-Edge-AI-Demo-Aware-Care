"""The specification checks fail when they should (#301, QA 2026-10-19).

check_contracts used `assert` (python -O skipped every check); jsonschema's FormatChecker skipped date-time and uri
without extra packages; check_contrast rounded before comparing (4.496 passed 4.5); the checkers globbed schemas
differently; monitoring crashed on sample size 0 and used another percentile than qualify_model.
"""
from __future__ import annotations

import ast
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_contrast  # noqa: E402
import monitoring  # noqa: E402
import spec_utils  # noqa: E402

HAVE_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None
class ContractChecks(unittest.TestCase):
    def test_no_check_relies_on_assert(self):
        tree = ast.parse((ROOT / "scripts/check_contracts.py").read_text())
        self.assertEqual([n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assert)], [])

    @unittest.skipUnless(shutil.which("uv"), "uv runs the documented jsonschema==4.25.1 invocation")
    def test_a_broken_contract_fails_even_under_python_O(self):
        tmp = Path(tempfile.mkdtemp(prefix="contracts-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "scripts").mkdir()
        for name in ("check_contracts.py", "spec_utils.py"):
            shutil.copy2(ROOT / "scripts" / name, tmp / "scripts" / name)
        shutil.copytree(ROOT / "spec", tmp / "spec", ignore=shutil.ignore_patterns("mockups", "*.png", "*.jpg"))
        (tmp / "tests/handoff").mkdir(parents=True)
        shutil.copy2(ROOT / "tests/handoff/contract-cases.json", tmp / "tests/handoff/contract-cases.json")
        api = tmp / "spec/api/openapi.json"
        api.write_text(api.read_text().replace('"openapi": "3.1.0"', '"openapi": "3.0.0"', 1))
        result = subprocess.run(["uv", "run", "--no-project", "--with", "jsonschema==4.25.1", "python", "-O",
                                 str(tmp / "scripts/check_contracts.py")], capture_output=True, text=True,
                                timeout=300)
        self.assertEqual(result.returncode, 1, result.stdout[-500:])
        self.assertIn("FAIL: OpenAPI version drift", result.stderr)


class Formats(unittest.TestCase):
    def test_date_time_is_checked(self):
        for value in ("2026-10-19T12:00:00Z", "2026-10-19t12:00:00.123+02:00", "2016-12-31T23:59:60Z"):
            self.assertTrue(spec_utils.is_date_time(value), value)
        for value in ("nonsense", "2026-10-19", "2026-10-19T12:00:00", "2026-02-30T00:00:00Z",
                      "2026-10-19T24:00:00Z", "2026-10-19T12:00:00+25:00", "2026-10-19 12:00:00Z"):
            self.assertFalse(spec_utils.is_date_time(value), value)
        self.assertTrue(spec_utils.is_date_time(5))  # formats apply to strings only

    def test_uri_is_checked(self):
        for value in ("https://example.org/a?b=c#d", "urn:isbn:0451450523", "mailto:a@example.org",
                      "http://[::1]:8080/v1"):
            self.assertTrue(spec_utils.is_uri(value), value)
        for value in ("not a uri", "/relative/path", "example.org", "http://x/%zz", "https://a#b#c", ""):
            self.assertFalse(spec_utils.is_uri(value), value)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema is not installed for this interpreter")
    def test_the_checker_rejects_bad_formats_without_extra_packages(self):
        checker = spec_utils.format_checker()
        self.assertFalse(checker.conforms("nonsense", "date-time"))
        self.assertFalse(checker.conforms("not a uri", "uri"))
        self.assertTrue(checker.conforms("2026-10-19T12:00:00Z", "date-time"))

    def test_every_validator_in_the_repository_uses_the_strict_checker(self):
        users = ["scripts/check_contracts.py", "scripts/qualify_model.py", "tests/acceptance/conftest.py",
                 "tests/acceptance/test_R12.py"]
        for relative in users:
            text = (ROOT / relative).read_text()
            self.assertNotIn("FormatChecker()", text, relative)
            self.assertIn("format_checker()", text, relative)


class SchemaGlob(unittest.TestCase):
    def test_the_checkers_read_the_same_schema_files_including_nested_ones(self):
        tmp = Path(tempfile.mkdtemp(prefix="schemas-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        nested = tmp / "spec/contracts/extra/x.schema.json"
        nested.parent.mkdir(parents=True)
        nested.write_text('{"type": "object", "additionalProperties": false}')
        self.assertIn(nested, spec_utils.schema_files(tmp))
        for relative in ("scripts/check_contracts.py", "scripts/check_traceability.py"):
            text = (ROOT / relative).read_text()
            self.assertIn("schema_files(", text, relative)
            self.assertNotIn('glob("*.schema.json")', text, relative)
            self.assertNotIn("glob('*.schema.json')", text, relative)


class Contrast(unittest.TestCase):
    def test_the_raw_ratio_is_compared(self):
        with mock.patch.object(check_contrast, "ratio", return_value=4.496):
            rows = check_contrast.check(check_contrast.CSS.read_text())
        text = [r for r in rows if r["minimum"] == 4.5]
        self.assertTrue(text)
        self.assertTrue(all(not r["passed"] for r in text))
        self.assertTrue(all(r["ratio"] == 4.49 for r in text))  # shown truncated, never as 4.5


class Monitoring(unittest.TestCase):
    CASES = [{"id": f"c{i}", "kind": "common"} for i in range(10)] + \
            [{"id": f"b{i}", "kind": "borderline"} for i in range(5)]

    def test_a_sample_size_below_one_is_refused(self):
        for size in (0, -3):
            with self.assertRaises(ValueError):
                monitoring.sample_cases(self.CASES, "2026-11", size)
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as caught:
            monitoring.main(["review-sample", "--month", "2026-11", "--size", "0", "--out", "x.json"])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(len(monitoring.sample_cases(self.CASES, "2026-11", 1)), 1)

    def test_percentiles_use_the_qualification_definition(self):
        # qualify_model.pct: linear interpolation between closest ranks, rounded to 3 decimals.
        values = [4.0, 1.0, 3.0, 2.0]
        self.assertEqual(monitoring._percentile(values, 0.5), 2.5)
        self.assertEqual(monitoring._percentile(values, 0.95), 3.85)
        self.assertEqual(monitoring._percentile([7.0], 0.95), 7.0)
        self.assertIsNone(monitoring._percentile([], 0.5))
        source = (ROOT / "scripts/qualify_model.py").read_text()
        self.assertIn("k = (len(ordered) - 1) * q", source)  # the definition both share


if __name__ == "__main__":
    unittest.main()
