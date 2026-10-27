#!/usr/bin/env python3
"""Decide a dependency audit from the tools' JSON reports and the dated ignore list (#369; M12, R34/R40).

  npm     an `npm audit --omit=dev --json` report of apps/web (production dependencies). Advisories rated high or
          critical fail the audit.
  python  a `pip-audit --format json` report of the API's locked requirements (exported from apps/api/uv.lock).
          pip-audit reports no severity, so every known vulnerability fails the audit.

An advisory passes only through an entry in `.audit-ignore.json` with its id (or an alias), the ecosystem, the
package, a reason and an expiry date that has not passed. An expired or malformed entry fails the audit, as does a
missing, empty or unreadable report (a network failure is never a pass). Standard library only; the tools run in the
CI "Dependency audit" job, and this script never contacts the network.

Usage: dependency_audit.py npm|python REPORT.json [--ignore-file .audit-ignore.json] [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILING_NPM = {"high", "critical"}
ECOSYSTEMS = {"npm": "npm", "python": "pypi"}
GHSA = re.compile(r"GHSA(?:-[0-9a-z]{4}){3}")


class AuditError(Exception):
    pass


def load_ignores(path: Path, today: date) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{path.name}: unreadable ({exc})") from exc
    entries = data.get("ignores") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise AuditError(f"{path.name}: needs an object with an \"ignores\" array")
    for n, entry in enumerate(entries, 1):
        where = f"{path.name} entry {n}"
        if not isinstance(entry, dict):
            raise AuditError(f"{where}: must be an object")
        for key in ("id", "ecosystem", "package", "reason", "expires"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise AuditError(f"{where}: \"{key}\" is required")
        if entry["ecosystem"] not in ECOSYSTEMS.values():
            raise AuditError(f"{where}: ecosystem must be one of {sorted(ECOSYSTEMS.values())}")
        try:
            expires = date.fromisoformat(entry["expires"])
        except ValueError as exc:
            raise AuditError(f"{where}: expires must be YYYY-MM-DD") from exc
        if expires < today:
            raise AuditError(f"{where} ({entry['id']}, {entry['package']}) expired on {entry['expires']}; "
                             "fix the dependency or renew the entry with a new reason")
    return entries


def read_report(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if text.strip() else None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{path}: no readable report ({exc})") from exc
    if not isinstance(data, dict):
        raise AuditError(f"{path}: empty or not a JSON object; the audit did not run")
    return data


def npm_findings(data: dict) -> tuple[list[dict], int]:
    """Every advisory in the report (each package's `via` objects), keyed by its GHSA id where there is one."""
    if "error" in data or not isinstance(data.get("vulnerabilities"), dict) or "metadata" not in data:
        raise AuditError(f"npm audit did not produce a report: {json.dumps(data.get('error', data))[:300]}")
    found: dict[tuple, dict] = {}
    for package, item in data["vulnerabilities"].items():
        for via in item.get("via", []):
            if not isinstance(via, dict):
                continue                                   # a transitive pointer; that package lists the advisory
            match = GHSA.search(str(via.get("url", "")))
            ident = match.group(0) if match else f"npm-{via.get('source')}"
            name = via.get("name", package)
            found[(ident, name)] = {"id": ident, "aliases": [], "package": name, "severity": via.get("severity"),
                                    "title": via.get("title", ""), "fails": via.get("severity") in FAILING_NPM}
    counts = data["metadata"].get("dependencies", {})
    return sorted(found.values(), key=lambda f: (f["package"], f["id"])), counts.get("prod", counts.get("total", 0))


def python_findings(data: dict) -> tuple[list[dict], int]:
    deps = data.get("dependencies")
    if not isinstance(deps, list):
        raise AuditError("pip-audit did not produce a report (no dependencies array)")
    found = []
    for dep in deps:
        if dep.get("skip_reason"):
            raise AuditError(f"pip-audit skipped {dep.get('name')}: {dep['skip_reason']}")
        for vuln in dep.get("vulns", []):
            found.append({"id": vuln["id"], "aliases": vuln.get("aliases", []), "package": dep["name"],
                          "severity": "unrated", "title": (vuln.get("description") or "")[:120],
                          "fails": True, "fix": vuln.get("fix_versions", [])})
    return found, len(deps)


def ignored_by(finding: dict, ecosystem: str, ignores: list[dict]) -> dict | None:
    ids = {finding["id"], *finding["aliases"]}
    for entry in ignores:
        if (entry["ecosystem"] == ecosystem and entry["id"] in ids
                and entry["package"].lower() == finding["package"].lower()):
            return entry
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=sorted(ECOSYSTEMS))
    parser.add_argument("report", type=Path)
    parser.add_argument("--ignore-file", type=Path, default=ROOT / ".audit-ignore.json")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    ecosystem = ECOSYSTEMS[args.kind]
    try:
        ignores = load_ignores(args.ignore_file, args.today)
        data = read_report(args.report)
        findings, audited = npm_findings(data) if args.kind == "npm" else python_findings(data)
    except AuditError as exc:
        print(f"AUDIT ERROR ({args.kind}): {exc}", file=sys.stderr)
        return 1
    failing = []
    for f in findings:
        entry = ignored_by(f, ecosystem, ignores)
        verdict = "FAIL" if f["fails"] and not entry else ("ignored" if entry else "below threshold")
        note = f" (ignored until {entry['expires']}: {entry['reason']})" if entry else ""
        print(f"{verdict}: {f['package']} {f['id']} [{f['severity']}] {f['title']}{note}")
        if verdict == "FAIL":
            failing.append(f)
    used = {(e["id"], e["package"].lower()) for e in ignores for f in findings
            if e["ecosystem"] == ecosystem and ignored_by(f, ecosystem, [e])}
    for entry in ignores:
        if entry["ecosystem"] == ecosystem and (entry["id"], entry["package"].lower()) not in used:
            print(f"note: {args.ignore_file.name} entry {entry['id']} ({entry['package']}) matched nothing; remove it")
    threshold = "high or critical" if args.kind == "npm" else "any known vulnerability (pip-audit has no severity)"
    print(f"{args.kind}: {audited} dependencies audited, {len(findings)} advisories, {len(failing)} failing "
          f"(threshold: {threshold}).")
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
