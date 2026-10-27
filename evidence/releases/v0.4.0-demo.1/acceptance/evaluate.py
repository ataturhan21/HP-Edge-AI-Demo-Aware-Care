"""Evaluate the #25 clause map against executed test reports (JUnit XML and Playwright JSON).

#366: the evaluator now lives in scripts/evaluate_acceptance.py. This file stays so that every release README that
cites this path keeps working: it runs that script with the same arguments and prints the same output.
Usage: evaluate.py clause-map.json report.xml|report.json ... > evaluation.json
"""
import importlib.util
import sys
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[4] / "scripts" / "evaluate_acceptance.py"
_spec = importlib.util.spec_from_file_location("evaluate_acceptance", _SOURCE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

junit = _module.junit
playwright = _module.playwright
evaluate = _module.evaluate
main = _module.main

if __name__ == "__main__":
    raise SystemExit(main())
