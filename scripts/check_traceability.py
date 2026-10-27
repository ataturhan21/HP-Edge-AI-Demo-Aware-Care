#!/usr/bin/env python3
"""Check the stable specification identities and their mappings using only stdlib.

R01-R40, the 25 screens and routes, M01-M12, the 33 API operations, the acceptance registry and spec/traceability.yaml
must agree with each other, and every path they name must be safe (and exist once the item is implemented). It runs
no application tests and establishes no medical correctness. The spec hash lock and the registration of every runtime
file were retired with the lean delivery rules (ADR-019).
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import sys
from typing import Any

from spec_utils import SpecError, read_json, safe_path, schema_files

REQUIREMENTS = {f"R{i:02}" for i in range(1, 41)}
MODULES = {f"M{i:02}" for i in range(1, 13)}
FIXTURES = {f"F{i:02}" for i in range(1, 13)}
BENEFITS = {f"B{i:02}" for i in range(1, 9)}
SCREENS = {f"W{i:02}" for i in range(1, 7)} | {f"A{i:02}" for i in range(1, 17)} | {f"O{i:02}" for i in range(1, 4)}
OPERATIONS = set("createSession deleteSession getProfile saveProfile createCase listCases getCase editCase deleteCase uploadRecord listRecords reviewFact nextQuestion saveAnswer confirmReview generateGuidance getGuidance getCaseSources searchProviders getProvider createExport downloadExport getJob getSettings updateSettings deleteAllHealthData getRuntime getControls loadScenario resetDemo getReadiness getTelemetry getLogs".split())
STATES = {"planned", "implemented", "verified"}
TEST_STATES = {"NOT_EXECUTED", "PASSED", "FAILED", "BLOCKED", "ERROR", "SKIPPED"}
EXPECTED_ROUTES = {
    "W01": "/", "W02": "/how-it-works", "W03": "/healthcare", "W04": "/privacy", "W05": "/help", "W06": "/telemetry",
    "A01": "/app/start", "A02": "/app/profile", "A03": "/app/new", "A04": "/app/cases/:caseId/records",
    "A05": "/app/cases/:caseId/questions", "A06": "/app/cases/:caseId/review", "A07": "/app/cases/:caseId/guidance",
    "A08": "/app/cases/:caseId/sources", "A09": "/app/cases/:caseId/preferences", "A10": "/app/cases/:caseId/doctors",
    "A11": "/app/cases/:caseId/doctors/:providerId", "A12": "/app/cases/:caseId/summary", "A13": "/app/history",
    "A14": "/app/settings", "A15": "/app/cases/:caseId/urgent", "A16": "/app/limits",
    "O01": "/presenter/runtime", "O02": "/presenter/controls", "O03": "/presenter/scenarios",
}


class Checks:
    def __init__(self, root: Path):
        self.root = root
        self.errors: list[str] = []
        self.planned_paths: set[str] = set()

    def require(self, condition: Any, message: str) -> bool:
        if not condition:
            self.errors.append(message)
        return bool(condition)

    def rows(self, payload: Any, key: str, label: str) -> list[dict]:
        rows = payload.get(key) if isinstance(payload, dict) else None
        if not self.require(isinstance(rows, list), f"{label}: {key} must be an array"):
            return []
        self.require(all(isinstance(x, dict) for x in rows), f"{label}: all {key} entries must be objects")
        return [x for x in rows if isinstance(x, dict)]

    def exact_ids(self, rows: list[dict], key: str, expected: set[str], label: str) -> dict:
        ids = [row.get(key) for row in rows]
        strings = [value for value in ids if isinstance(value, str)]
        self.require(len(strings) == len(ids), f"{label}: missing/non-string {key}")
        dupes = sorted(k for k, count in Counter(strings).items() if count > 1)
        self.require(not dupes, f"{label}: duplicate IDs {dupes}")
        self.require(set(strings) == expected,
                     f"{label}: missing={sorted(expected-set(strings))}, unknown={sorted(set(strings)-expected)}")
        return {row[key]: row for row in rows if isinstance(row.get(key), str)}

    def refs(self, values: Any, allowed: set[str], label: str) -> list[str]:
        if not self.require(isinstance(values, list) and all(isinstance(x, str) for x in values),
                            f"{label}: must be an array of string IDs"):
            return []
        self.require(len(values) == len(set(values)), f"{label}: duplicate reference")
        self.require(set(values) <= allowed, f"{label}: unknown IDs {sorted(set(values)-allowed)}")
        return values

    def path(self, value: Any, label: str, required: bool = False) -> bool:
        try:
            path = safe_path(self.root, value, must_exist=required)
            if not required and not path.is_file():
                self.planned_paths.add(value)
            return True
        except SpecError as exc:
            self.errors.append(f"{label}: {exc}")
            return False

    def path_list(self, values: Any, label: str, required: bool = False) -> list[str]:
        if not self.require(isinstance(values, list), f"{label}: must be an array of paths"):
            return []
        return [value for value in values if self.path(value, label, required)]


def check(root: Path) -> Checks:
    c = Checks(root)
    documents = {name: read_json(root, path) for name, path in {
        "requirements": "spec/requirements.json", "screens": "spec/screens.json",
        "modules": "spec/modules.json", "acceptance": "spec/acceptance.json", "trace": "spec/traceability.yaml",
        "registry": "spec/contracts/registry.json", "operations": "spec/api/operations.json",
        "scenarios": "spec/scenarios.json", "benefits": "spec/benefits.json",
        "openapi": "spec/api/openapi.json",
    }.items()}
    version = documents["screens"].get("spec_version") if isinstance(documents["screens"], dict) else None
    c.require(isinstance(version, str) and bool(version), "spec/screens.json must declare spec_version")
    for name in ("requirements", "screens", "modules", "acceptance", "trace", "registry", "operations", "scenarios", "benefits"):
        c.require(isinstance(documents[name], dict) and documents[name].get("spec_version") == version,
                  f"{name}: spec_version disagrees with the shared baseline")
    reqs = c.exact_ids(c.rows(documents["requirements"], "requirements", "requirements"), "id", REQUIREMENTS, "requirements")
    screens = c.exact_ids(c.rows(documents["screens"], "screens", "screens"), "id", SCREENS, "screens")
    modules = c.exact_ids(c.rows(documents["modules"], "modules", "modules"), "id", MODULES, "modules")
    operations = c.exact_ids(c.rows(documents["operations"], "operations", "operations"), "operation_id", OPERATIONS, "operations")
    tests = c.exact_ids(c.rows(documents["acceptance"], "tests", "acceptance"), "id", {"T-"+r for r in REQUIREMENTS}, "acceptance")
    fixture_catalogue = c.exact_ids(c.rows(documents["scenarios"], "scenarios", "scenario catalogue"), "id", FIXTURES, "scenario catalogue")
    benefits = c.exact_ids(c.rows(documents["benefits"], "benefits", "benefits"), "id", BENEFITS, "benefits")
    product = safe_path(root, "spec/product.md", must_exist=True).read_text(encoding="utf-8")
    for fid, fixture in fixture_catalogue.items():
        text = fixture.get("canonical_scenario_and_required_result")
        c.require(isinstance(text, str) and bool(text) and text in product, f"{fid}: canonical scenario clause is absent from spec/product.md")
    for bid, benefit in benefits.items():
        c.refs(benefit.get("requirement_ids"), REQUIREMENTS, f"{bid} requirements")
        for field in ("beneficiary", "hypothesis", "suggested_measure"):
            text = benefit.get(field)
            c.require(isinstance(text, str) and bool(text) and text in product, f"{bid}: source {field} is absent from spec/product.md")
    schema_rows = c.rows(documents["registry"], "schemas", "contracts registry")
    schema_names = [row.get("name") for row in schema_rows]
    valid_schemas = {name for name in schema_names if isinstance(name, str)}
    c.require(len(valid_schemas) == len(schema_names), "contracts registry: missing or duplicate schema names")
    for row in schema_rows:
        c.path("spec/contracts/"+str(row.get("file", "")), f"schema {row.get('name')}", required=True)
    present = {p.relative_to(root/"spec/contracts").as_posix() for p in schema_files(root)}  # #301
    c.require(present == {r.get("file") for r in schema_rows}, "contracts registry does not list exactly the schema files present")
    trace = documents["trace"].get("requirements", {})
    c.require(isinstance(trace, dict) and set(trace) == REQUIREMENTS, "traceability: expected exactly R01-R40")
    if not isinstance(trace, dict):
        trace = {}

    for rid, req in reqs.items():
        state = req.get("status")
        c.require(state in STATES, f"{rid}: invalid status {state!r}")
        module = req.get("module_id")
        c.require(module in MODULES, f"{rid}: unknown module {module!r}")
        ids = c.refs(req.get("screen_ids"), SCREENS, f"{rid} screens")
        expected_screens = {sid for sid, s in screens.items() if rid in s.get("requirements", [])}
        c.require(set(ids) == expected_screens, f"{rid}: screen/requirement associations are not bidirectional")
        c.refs(req.get("api_operation_ids"), OPERATIONS, f"{rid} operations")
        c.path_list(req.get("planned_implementation_paths"), f"{rid} implementation", state != "planned")
        c.require(req.get("test_id") == "T-"+rid, f"{rid}: primary test alias must be T-{rid}")
        test_path = f"tests/acceptance/test_{rid}.py"
        c.require(req.get("test_path") == test_path, f"{rid}: canonical test path changed")
        c.path(test_path, f"{rid} test", state != "planned")
        if safe_path(root, test_path).is_file():
            contents = safe_path(root, test_path).read_text(encoding="utf-8")
            c.require(re.search(r"\b"+re.escape(rid)+r"\b", contents),
                      f"{rid}: existing acceptance test {test_path} must cite its requirement ID (this does not establish test semantics)")
        c.require(bool(req.get("canonical_acceptance")) and req["canonical_acceptance"] in product,
                  f"{rid}: canonical acceptance clause is absent from spec/product.md")
        c.require((rid+" "+str(req.get("title", ""))) in product, f"{rid}: title is absent from spec/product.md")
        item = trace.get(rid)
        if not c.require(isinstance(item, dict), f"{rid}: trace entry must be an object"):
            continue
        c.require(item.get("owner") == module, f"{rid}: trace owner differs from requirement owner")
        c.require(item.get("status") == state, f"{rid}: trace/requirement statuses differ")
        trace_screens = c.refs(item.get("screens"), SCREENS, f"{rid} trace screens")
        c.require(set(trace_screens) == set(ids), f"{rid}: trace screen set differs")
        trace_ops = c.refs(item.get("operations"), OPERATIONS, f"{rid} trace operations")
        c.require(set(trace_ops) == set(req.get("api_operation_ids", [])), f"{rid}: trace operation set differs")
        c.refs(item.get("contracts"), valid_schemas, f"{rid} contracts")
        trace_benefits = c.refs(item.get("benefits", []), BENEFITS, f"{rid} benefits")
        c.require(set(trace_benefits) == {bid for bid, benefit in benefits.items() if rid in benefit.get("requirement_ids", [])},
                  f"{rid}: benefit/requirement associations are not bidirectional")
        c.require(bool(item.get("section")), f"{rid}: trace needs a source section")
        code = c.path_list(item.get("code"), f"{rid} trace code", state != "planned")
        c.require(bool(code), f"{rid}: trace needs at least 1 implementation path")
        trace_tests = c.path_list(item.get("tests"), f"{rid} trace tests", state != "planned")
        c.require(test_path in trace_tests, f"{rid}: trace omits its canonical acceptance test")
        if state == "verified":
            c.require(tests.get("T-"+rid, {}).get("status") == "PASSED", f"{rid}: verified requires executed PASSED acceptance status")

    for sid, screen in screens.items():
        c.require(screen.get("route") == EXPECTED_ROUTES[sid], f"{sid}: route differs from baseline v2.0")
        c.require(screen.get("module") in MODULES, f"{sid}: unknown module")
        c.refs(screen.get("requirements"), REQUIREMENTS, f"{sid} requirements")
        state = screen.get("implementation_status")
        c.require(state in STATES, f"{sid}: invalid implementation status")
        c.require(screen.get("implementation_path") == f"apps/web/src/screens/{sid}.tsx", f"{sid}: canonical screen path changed")
        c.require(screen.get("test_path") == f"tests/ui/{sid}.spec.ts", f"{sid}: canonical UI test path changed")
        c.path(screen.get("implementation_path"), f"{sid} implementation", state != "planned")
        c.path(screen.get("test_path"), f"{sid} test", state != "planned")
        for action in screen.get("action_contracts", []):
            if isinstance(action, dict):
                c.refs(action.get("target_screen_ids", []), SCREENS, f"{sid} action targets")
        mockups = screen.get("mockups", {})
        if c.require(isinstance(mockups, dict), f"{sid}: mockups must be an object"):
            for key in ("desktop", "mobile"):
                c.path(mockups.get(key), f"{sid} {key} mockup", required=True)
            states = mockups.get("states", {})
            if c.require(isinstance(states, dict), f"{sid}: mockup states must be an object"):
                for name, path in states.items():
                    c.path(path, f"{sid} {name} mockup", required=True)

    for mid, module in modules.items():
        state = module.get("status")
        c.require(state in STATES, f"{mid}: invalid status {state!r}")
        ids = c.refs(module.get("requirements"), REQUIREMENTS, f"{mid} requirements")
        c.require(set(ids) == {rid for rid, r in reqs.items() if r.get("module_id") == mid}, f"{mid}: module ownership is not bidirectional")
        c.refs(module.get("screen_ids"), SCREENS, f"{mid} screens")
        own_ops = c.refs(module.get("owned_api_operation_ids"), OPERATIONS, f"{mid} operations")
        c.require(set(own_ops) == {oid for oid, op in operations.items() if op.get("owner") == mid}, f"{mid}: API ownership differs")
        c.path(module.get("planned_service_path"), f"{mid} service", state != "planned")

    found_openapi: dict[str, tuple[str, str, dict]] = {}
    for path, methods in documents["openapi"].get("paths", {}).items():
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                continue
            oid = operation.get("operationId")
            c.require(oid not in found_openapi, f"OpenAPI: duplicate operationId {oid}")
            found_openapi[oid] = (method.upper(), "/api/v1"+path, operation)
    c.require(set(found_openapi) == OPERATIONS, "OpenAPI must expose exactly the 33 operation IDs (31 baseline + getTelemetry, ADR-017 + getLogs, #548)")
    for oid, operation in operations.items():
        c.require(operation.get("owner") in MODULES, f"{oid}: unknown owner")
        supporting = c.refs(operation.get("requirements"), REQUIREMENTS, f"{oid} requirements")
        c.require(set(supporting) == {rid for rid, req in reqs.items() if oid in req.get("api_operation_ids", [])},
                  f"{oid}: operation/requirement associations are not bidirectional")
        for key in ("request_schema", "response_schema"):
            value = operation.get(key)
            c.require(value is None or value in valid_schemas, f"{oid}: unknown {key} {value!r}")
        if oid in found_openapi:
            method, path, wire = found_openapi[oid]
            c.require((method, path) == (operation.get("method"), operation.get("path")), f"{oid}: OpenAPI method/path mismatch")
            c.require(wire.get("x-owner-module") == operation.get("owner"), f"{oid}: OpenAPI owner mismatch")
            c.require(wire.get("x-requirement-ids") == operation.get("requirements"), f"{oid}: OpenAPI requirement mapping mismatch")

    all_scenario_ids: list[str] = []
    for tid, test in tests.items():
        rid = tid[2:]
        c.require(test.get("requirement_id") == rid, f"{tid}: requirement mapping differs")
        c.require(test.get("test_path") == f"tests/acceptance/test_{rid}.py", f"{tid}: wrong canonical test path")
        c.require(test.get("canonical_acceptance") == reqs.get(rid, {}).get("canonical_acceptance"), f"{tid}: canonical clause differs")
        c.require(test.get("status") in TEST_STATES, f"{tid}: unknown execution status")
        if test.get("status") == "PASSED":
            c.path(test.get("test_path"), f"{tid} executed test", required=True)
        scenarios = c.rows(test, "scenarios", tid)
        c.require(bool(scenarios), f"{tid}: at least 1 actionable scenario is required")
        for scenario in scenarios:
            scenario_id = scenario.get("id")
            c.require(isinstance(scenario_id, str) and scenario_id.startswith(tid+"-S"), f"{tid}: invalid scenario ID")
            if isinstance(scenario_id, str):
                all_scenario_ids.append(scenario_id)
            for key in ("given", "when"):
                c.require(isinstance(scenario.get(key), str) and bool(scenario[key].strip()), f"{scenario_id}: missing {key}")
            c.require(isinstance(scenario.get("then"), list) and bool(scenario["then"])
                      and all(isinstance(x, str) and x.strip() for x in scenario["then"]), f"{scenario_id}: then needs concrete assertions")
            c.require(scenario.get("status") in TEST_STATES, f"{scenario_id}: unknown execution status")
            c.refs(scenario.get("mock_scenario_ids", []), {"routine", "selfcare", "urgent", "unsupported", "nomatch", "failure"}, f"{scenario_id} mock IDs")
            c.refs(scenario.get("source_fixture_ids", []), FIXTURES, f"{scenario_id} source fixture IDs")
            for fixture in scenario.get("fixture_refs", []):
                c.path(fixture.get("path") if isinstance(fixture, dict) else fixture, f"{scenario_id} fixture", required=True)
            if test.get("status") == "PASSED":
                c.require(scenario.get("status") == "PASSED", f"{tid}: not all scenarios are executed PASSED")
    c.require(len(all_scenario_ids) == len(set(all_scenario_ids)), "Acceptance scenario IDs must be globally unique")

    return c


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = check(args.root.resolve())
    except (SpecError, OSError, UnicodeError, AttributeError, TypeError, KeyError) as exc:
        print(f"TRACEABILITY ERROR: {exc}", file=sys.stderr)
        return 1
    if result.errors:
        print(f"TRACEABILITY FAILED: {len(result.errors)} issue(s)", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("PASS: specification identities, mappings, mockup assets and paths are consistent.")
    print(f"40 requirements / 25 screens / 12 modules / 33 API operations. Missing planned paths: {len(result.planned_paths)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
