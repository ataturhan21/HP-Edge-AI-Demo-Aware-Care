#!/usr/bin/env python3
"""Check summaries and release manifests for the delivery workflows (M12; R37, R40).

  summarize  Count executed results from test reports (pytest JUnit XML and the
             Playwright JSON report) next to the acceptance registry statuses.
             Registry records that say NOT_EXECUTED are reported as such and never
             counted as passed; a missing report is NOT_RUN, not a pass.
  manifest   Assemble release-manifest.json, package-digests.txt, the annotated
             tag message and draft release notes for .github/workflows/release.yml.
  extract    Read the manifest back out of an annotated tag message
             (.github/workflows/deploy-nano.yml).

Standard library only.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_SCHEMA = "aware-care-release-manifest/1"
BEGIN = "-----BEGIN AWARE CARE RELEASE MANIFEST-----"
END = "-----END AWARE CARE RELEASE MANIFEST-----"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def junit_counts(path: Path | None) -> dict:
    if not path or not path.exists() or path.stat().st_size == 0:
        return {"result": "NOT_RUN", "report": str(path) if path else None}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    totals = collections.Counter()
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            totals[key] += int(suite.get(key, 0))
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    failed = totals["failures"] + totals["errors"]
    return {"result": "PASSED" if failed == 0 and passed > 0 else "FAILED", "report": str(path),
            "executed": totals["tests"] - totals["skipped"], "passed": passed, "failed": failed,
            "skipped": totals["skipped"]}


def playwright_counts(path: Path | None) -> dict:
    if not path or not path.exists() or path.stat().st_size == 0:
        return {"result": "NOT_RUN", "report": str(path) if path else None}
    stats = json.loads(path.read_text()).get("stats", {})
    passed, failed = stats.get("expected", 0), stats.get("unexpected", 0)
    flaky, skipped = stats.get("flaky", 0), stats.get("skipped", 0)
    ok = failed == 0 and flaky == 0 and passed > 0
    return {"result": "PASSED" if ok else "FAILED", "report": str(path), "executed": passed + failed + flaky,
            "passed": passed, "failed": failed, "flaky": flaky, "skipped": skipped}


def registry_counts(path: Path) -> dict:
    tests = json.loads(path.read_text())["tests"]
    primary = collections.Counter(t["status"] for t in tests)
    scenarios = collections.Counter(s["status"] for t in tests for s in t.get("scenarios", []))
    return {"primary_tests": dict(sorted(primary.items())), "scenarios": dict(sorted(scenarios.items())),
            "note": ("Registry statuses are unchanged by this run. NOT_EXECUTED records are not counted as passed; "
                     "requirements become verified only with release evidence (evidence/README.md).")}


def summary_markdown(title: str, summary: dict) -> str:
    lines = [f"### {title}", "", "| Check | Result | Executed | Passed | Failed | Skipped |", "|---|---|---|---|---|---|"]
    for name, row in summary["executed_checks"].items():
        lines.append(f"| {name} | **{row['result']}** | {row.get('executed', '-')} | {row.get('passed', '-')} | "
                     f"{row.get('failed', '-')} | {row.get('skipped', '-')} |")
    reg = summary["acceptance_registry"]
    fmt = lambda counts: ", ".join(f"{k}: {v}" for k, v in counts.items())  # noqa: E731
    lines += ["", f"Acceptance registry (`spec/acceptance.json`): primary tests {fmt(reg['primary_tests'])}; "
                  f"scenarios {fmt(reg['scenarios'])}.", "", f"> {reg['note']}"]
    return "\n".join(lines) + "\n"


def cmd_summarize(args: argparse.Namespace) -> int:
    summary = {"executed_checks": {"backend_acceptance_mock": junit_counts(args.junit)},
               "acceptance_registry": registry_counts(args.acceptance)}
    if args.ui_json is not None or args.require_ui:
        summary["executed_checks"]["browser_ui_mock"] = playwright_counts(args.ui_json)
    text = summary_markdown(args.title, summary)
    if args.out_md:
        args.out_md.write_text(text)
    if args.out_json:
        args.out_json.write_text(json.dumps(summary, indent=2) + "\n")
    print(text)
    failed = [k for k, v in summary["executed_checks"].items() if v["result"] != "PASSED"]
    return 1 if failed and args.fail_on_failure else 0


def buildx_digest(path: Path) -> str:
    digest = json.loads(path.read_text()).get("containerimage.digest")
    if not digest or not DIGEST.match(digest):
        raise SystemExit(f"{path}: no containerimage.digest")
    return digest


def cmd_manifest(args: argparse.Namespace) -> int:
    backend = junit_counts(args.junit)
    if backend["result"] != "PASSED":
        raise SystemExit("backend acceptance (mock) did not pass on the release build; refusing to write a manifest")
    packages = {}
    for role, repo, meta in (("api", args.api_repo, args.api_metadata), ("web", args.web_repo, args.web_metadata)):
        digest = buildx_digest(meta)
        packages[role] = {"image": repo, "digest": digest, "ref": f"{repo}@{digest}", "platform": args.platform}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "product": "Aware Care",
        "version": args.version,
        "tag": args.tag,
        "app_commit": args.commit,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": args.platform,
        "packages": packages,
        "verified_by": {"ci_run_url": args.ci_run_url, "release_run_url": args.release_run_url},
        "release_build_checks": {"traceability": "PASSED", "contracts": "PASSED",
                                 "backend_acceptance_mock": backend},
        "acceptance_registry": registry_counts(args.acceptance),
        "deployable_modes": ["mock", "local"],
        "local_mode_note": ("Local mode needs a reviewed pathway, approved corpus and pinned model manifest "
                            "(ADR-002 to ADR-004). Until then its readiness is unavailable and a local "
                            "deployment fails and rolls back; it never falls back to mock."),
        "status": "DRAFT_PRERELEASE",
        "note": ("Packages of a synthetic demonstration build. Not release verification evidence and not for "
                 "clinical use; requirement statuses are unchanged."),
    }
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "package-digests.txt").write_text(
        "".join(f"{p['digest']}  {p['image']}  {p['platform']}\n" for p in packages.values()))
    (out / "tag-message.txt").write_text(
        f"Aware Care {args.version} (draft prerelease)\n\nCommit {args.commit}\n\n{BEGIN}\n"
        f"{json.dumps(manifest, indent=2)}\n{END}\n")
    reg = manifest["acceptance_registry"]
    notes = [
        f"Aware Care **{args.version}**: linux/arm64 packages built from `{args.commit}`.",
        "",
        "> Synthetic demonstration build. Not for clinical use. This draft prerelease is not release verification "
        "evidence; requirement statuses remain unchanged.",
        "",
        "| Package | Digest |", "|---|---|",
        *[f"| `{p['image']}` | `{p['digest']}` |" for p in packages.values()],
        "",
        f"Verified CI run for this commit: {args.ci_run_url}",
        "",
        "Release build checks on linux/arm64: traceability PASSED, contracts PASSED, backend acceptance (mock) "
        f"{backend['passed']} passed / {backend['failed']} failed / {backend['skipped']} skipped.",
        "",
        f"Acceptance registry: primary tests {reg['primary_tests']}, scenarios {reg['scenarios']} "
        "(NOT_EXECUTED is not counted as passed).",
        "",
        "Deploy (manual, environment `demo-zgx-nano`):",
        "```bash",
        f"gh workflow run deploy-nano.yml --repo {args.repository} --ref {args.tag} -f mode=mock",
        "```",
        "See `spec/engineering/08-delivery-and-nano-runbook.md` for local mode, evidence and rollback.",
    ]
    (out / "release-notes.md").write_text("\n".join(notes) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    text = args.message.read_text()
    if BEGIN not in text or END not in text:
        raise SystemExit("tag message carries no release manifest; was this tag created by release.yml?")
    manifest = json.loads(text.split(BEGIN, 1)[1].split(END, 1)[0])
    problems = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        problems.append("unknown manifest schema")
    if manifest.get("tag") != args.tag:
        problems.append("manifest tag does not match the dispatched tag")
    if manifest.get("app_commit") != args.commit:
        problems.append("manifest commit does not match the tagged commit")
    for role in ("api", "web"):
        package = manifest.get("packages", {}).get(role, {})
        if not DIGEST.match(package.get("digest", "")) or package.get("ref") != f"{package.get('image')}@{package.get('digest')}":
            problems.append(f"{role} package is not pinned by digest")
        if package.get("platform") != "linux/arm64":
            problems.append(f"{role} package is not linux/arm64")
    if problems:
        raise SystemExit("; ".join(problems))
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"tag": manifest["tag"], "app_commit": manifest["app_commit"],
                      "api": manifest["packages"]["api"]["ref"], "web": manifest["packages"]["web"]["ref"]}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summarize")
    s.add_argument("--title", default="Aware Care checks")
    s.add_argument("--junit", type=Path)
    s.add_argument("--ui-json", type=Path)
    s.add_argument("--require-ui", action="store_true")
    s.add_argument("--acceptance", type=Path, default=Path("spec/acceptance.json"))
    s.add_argument("--out-md", type=Path)
    s.add_argument("--out-json", type=Path)
    s.add_argument("--fail-on-failure", action="store_true")

    m = sub.add_parser("manifest")
    for flag in ("--version", "--tag", "--commit", "--api-repo", "--web-repo", "--ci-run-url",
                 "--release-run-url", "--repository"):
        m.add_argument(flag, required=True)
    m.add_argument("--platform", default="linux/arm64")
    m.add_argument("--api-metadata", type=Path, required=True)
    m.add_argument("--web-metadata", type=Path, required=True)
    m.add_argument("--junit", type=Path, required=True)
    m.add_argument("--acceptance", type=Path, default=Path("spec/acceptance.json"))
    m.add_argument("--out-dir", type=Path, required=True)

    e = sub.add_parser("extract")
    e.add_argument("--message", type=Path, required=True)
    e.add_argument("--tag", required=True)
    e.add_argument("--commit", required=True)
    e.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    return {"summarize": cmd_summarize, "manifest": cmd_manifest, "extract": cmd_extract}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
