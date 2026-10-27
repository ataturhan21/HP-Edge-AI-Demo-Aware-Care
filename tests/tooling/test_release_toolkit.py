"""The acceptance evaluator scripts/evaluate_acceptance.py (#366), at its new and its old path.

Nothing here contacts GitHub, a device or a model.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALUATE = ROOT / "scripts/evaluate_acceptance.py"
OLD_EVALUATE = ROOT / "evidence/releases/v0.4.0-demo.1/acceptance/evaluate.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">
<testcase classname="tests.acceptance.test_R01" name="test_ok"/>
<testcase classname="tests.acceptance.test_R01" name="test_bad"><failure message="x"/></testcase>
</testsuite></testsuites>"""


def playwright_report(status: str = "passed") -> str:
    tests = [{"projectName": p, "status": "expected" if status == "passed" else "unexpected", "results": [{"status": status}]}
             for p in ("desktop-1440", "mobile-360")]
    return json.dumps({"suites": [{"title": "A01.spec.ts", "specs": [{"file": "A01.spec.ts", "title": "it works", "tests": tests}], "suites": []}]})


CLAUSES = {"scenarios": [
    {"id": "T-R01-S01", "evaluated": True, "clauses": [{"covered": True, "then": "a", "tests": [
        "tests/acceptance/test_R01.py::test_ok", "tests/ui/A01.spec.ts > it works"]}]},
    {"id": "T-R01-S02", "evaluated": True, "clauses": [{"covered": True, "then": "b", "tests": ["tests/acceptance/test_R01.py::test_bad"]}]},
    {"id": "T-R02-S01", "evaluated": False, "reason": "out of scope", "clauses": []},
]}


class EvaluateAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "map.json").write_text(json.dumps(CLAUSES))
        (self.tmp / "b.xml").write_text(JUNIT)
        (self.tmp / "u.json").write_text(playwright_report())
        self.args = [str(self.tmp / "map.json"), str(self.tmp / "b.xml"), str(self.tmp / "u.json")]

    def test_importable_at_both_paths_with_the_same_functions(self):
        new, old = load(EVALUATE, "evaluate_new"), load(OLD_EVALUATE, "evaluate_old")
        for name in ("junit", "playwright", "evaluate", "main"):
            self.assertTrue(callable(getattr(new, name)) and callable(getattr(old, name)), name)
        result = new.evaluate(CLAUSES, self.args[1:])
        self.assertEqual(old.evaluate(CLAUSES, self.args[1:]), result)
        self.assertEqual([s["status"] for s in result["scenarios"]], ["PASSED", "NOT_PASSED", "NOT_PASSED"])
        self.assertEqual(new.counts(result), (1, 3, 0))  # T-R01 needs both scenarios

    def test_both_paths_print_the_same_bytes(self):
        outs = [subprocess.run([sys.executable, str(p), *self.args], capture_output=True, text=True, check=True).stdout
                for p in (EVALUATE, OLD_EVALUATE)]
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(json.loads(outs[0])["schema"], "aware-care-acceptance-evaluation/1")
        self.assertTrue(outs[0].endswith("}\n"))

    def test_arguments(self):
        for args, code in (([], 2), ([self.args[0]], 2), (["--help"], 0), ([self.args[0], str(self.tmp / "none.xml")], 2)):
            r = subprocess.run([sys.executable, str(EVALUATE), *args], capture_output=True, text=True)
            self.assertEqual(r.returncode, code, args)

if __name__ == "__main__":
    unittest.main()
