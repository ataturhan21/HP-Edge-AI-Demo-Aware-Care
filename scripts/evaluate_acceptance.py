#!/usr/bin/env python3
"""Evaluate the #25/#55 clause map against executed test reports (JUnit XML and Playwright JSON).

A scenario is PASSED only when it was in scope, its given can be met, every then-clause is covered, and every
test named for it passed in every report of its kind (all parametrizations, both browser projects). Anything else
keeps its prior status and is listed with the reason. Primary T-Rxx records pass only when all their scenarios do.

Usage: evaluate_acceptance.py clause-map.json report.xml|report.json ... > evaluation.json
(the clause map in use: evidence/acceptance/55-clinician-scenarios/clause-map.json).

#366: moved here from the #25 evaluation's folder (evidence/releases/<its tag>/acceptance/evaluate.py), which keeps a
shim that runs this file, so the paths cited in older release READMEs still work. The output is unchanged byte for byte.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = "aware-care-acceptance-evaluation/1"
DEFAULT_CLAUSE_MAP = Path(__file__).resolve().parents[1] / "evidence/acceptance/55-clinician-scenarios/clause-map.json"


def junit(path):
    out = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        bad = any(child.tag in {"failure", "error", "skipped"} for child in case)
        base = f"tests/acceptance/{case.get('classname').split('.')[-1]}.py::"
        # A reference without parameters covers every parametrization; one with [id] names exactly one.
        for name in {case.get("name"), case.get("name").split("[")[0]}:
            out.setdefault(base + name, []).append("failed" if bad else "passed")
    return out


def playwright(path):
    out = {}

    def walk(suite):
        for spec in suite.get("specs", []):
            key = f"tests/ui/{Path(spec['file']).name}::{spec['title']}"
            for t in spec["tests"]:
                runs = t["results"]
                ok = t["status"] == "expected" and bool(runs) and all(r["status"] == "passed" for r in runs)
                verdict = "passed" if ok else f"{t['projectName']}:{t['status']}"
                if not runs:
                    verdict = f"{t['projectName']}:not executed"
                out.setdefault(key, []).append(verdict)
        for child in suite.get("suites", []):
            walk(child)
    for suite in json.loads(Path(path).read_text())["suites"]:
        walk(suite)
    return out


def evaluate(clause_map: dict, report_paths: list[str]) -> dict:
    """Return the evaluation document for a loaded clause map and report files (.xml = JUnit, else Playwright JSON)."""
    reports = {p: (junit(p) if p.endswith(".xml") else playwright(p)) for p in report_paths}
    kinds = {"tests/acceptance/": [p for p in reports if p.endswith(".xml")],
             "tests/ui/": [p for p in reports if p.endswith(".json")]}
    results, primary = [], {}
    for s in clause_map["scenarios"]:
        reasons, checked = [], {}
        if not s["evaluated"]:
            reasons.append(s["reason"])
        else:
            if s.get("given_not_met"):
                reasons.append(s["given_not_met"])
            if not s["clauses"]:
                reasons.append("No clauses defined for the scenario")
            for c in s["clauses"]:
                if not c["covered"]:
                    reasons.append(f"Clause not asserted: {c['then']} " + c.get("open", ""))
                if not c["tests"]:
                    reasons.append(f"No tests mapped to clause: {c['then']}")
                for test in c["tests"]:
                    paths = next((v for k, v in kinds.items() if test.startswith(k)), None)
                    if paths is None:
                        reasons.append(f"Unsupported test reference: {test}")
                        continue
                    if not paths:
                        reasons.append(f"No report of this kind for {test}")
                    for p in paths:
                        got = reports[p].get(test.replace(" > ", "::"))
                        verdict = "passed" if got and all(g == "passed" for g in got) else (got and ",".join(got) or "missing")
                        checked.setdefault(test, {})[Path(p).name] = verdict
                        if verdict != "passed":
                            reasons.append(f"{test}: {verdict} in {Path(p).name}")
        status = "PASSED" if s["evaluated"] and not reasons else "NOT_PASSED"
        results.append({"id": s["id"], "status": status, "reasons": sorted(set(reasons)), "tests": checked})
        primary.setdefault(s["id"].rsplit("-S", 1)[0], []).append(status)
    return {"schema": SCHEMA, "reports": [Path(p).name for p in reports],
            "scenarios": results,
            "primary": {k: ("PASSED" if all(v == "PASSED" for v in vs) and len(vs) == 2 else "NOT_PASSED")
                        for k, vs in primary.items()}}


def render(evaluation: dict) -> str:
    """The exact text the evaluator has always printed (json indent 1, newline from print)."""
    return json.dumps(evaluation, indent=1) + "\n"


def counts(evaluation: dict) -> tuple[int, int, int]:
    """(scenarios PASSED, scenarios evaluated in the map, primary records PASSED)."""
    passed = sum(s["status"] == "PASSED" for s in evaluation["scenarios"])
    return passed, len(evaluation["scenarios"]), sum(v == "PASSED" for v in evaluation["primary"].values())


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if len(args) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    clause_map = json.loads(Path(args[0]).read_text())
    missing = [p for p in args[1:] if not Path(p).is_file()]
    if missing:
        print(f"evaluate_acceptance: report not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    sys.stdout.write(render(evaluate(clause_map, args[1:])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

