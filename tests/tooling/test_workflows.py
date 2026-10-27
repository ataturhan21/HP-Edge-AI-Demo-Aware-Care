"""Workflow behaviour that must not regress (#298, #365, #369).

- ci: push CI for main is never cancelled; every job runs on a GitHub-hosted runner with read-only permissions and
  no secrets; the browser suite runs as shards merged into one report.
No network, no credentials: the step scripts are cut out of the workflow files and run with stand-ins on PATH.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"


def step_script(workflow: str, step_name: str) -> str:
    """The `run: |` block of the named step, dedented (the workflow files use a plain, regular layout)."""
    lines = (WORKFLOWS / workflow).read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {step_name}")
    run = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body) + "\n"


class CiConcurrency(unittest.TestCase):
    def test_push_runs_on_main_never_share_a_group(self):
        text = (WORKFLOWS / "ci.yml").read_text()
        group = re.search(r"^concurrency:\n  group: (.+)\n  cancel-in-progress: (.+)$", text, re.M)
        self.assertIn("github.run_id", group.group(1))             # one group per push run
        self.assertIn("github.event.pull_request.number", group.group(1))
        self.assertEqual(group.group(2), "${{ github.event_name == 'pull_request' }}")


def ci_jobs() -> dict[str, str]:
    """Each ci.yml job id and its text (the file's plain two-space layout; no YAML parser in the standard library)."""
    text = (WORKFLOWS / "ci.yml").read_text()
    body = text[text.index("\njobs:\n") + len("\njobs:\n"):]
    parts = re.split(r"^  ([a-z][a-z0-9-]*):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


class CiJobs(unittest.TestCase):
    """#365 (sharded browser suite, one merged report) and #369 (dependency audit) without weakening the gate."""

    def test_every_job_is_least_privilege_on_the_configured_runner(self):
        for job, text in ci_jobs().items():
            self.assertIn("    runs-on: ubuntu-latest\n", text, job)
            self.assertNotIn("vars.", text, job)
            self.assertIn("    permissions:\n      contents: read\n", text, job)
            self.assertNotIn("secrets.", text, job)
            self.assertIn("persist-credentials: false", text, job)

    def test_the_gate_requires_every_other_job(self):
        jobs = ci_jobs()
        needs = re.search(r"^    needs: \[(.+)\]$", jobs["gate"], re.M).group(1).split(", ")
        self.assertEqual(sorted(needs), sorted(set(jobs) - {"gate"}))
        self.assertIn("if: always()", jobs["gate"])
        self.assertIn("all(.[]; .result == \"success\")", jobs["gate"])

    def test_the_browser_suite_runs_as_shards_of_one_matrix(self):
        ui = ci_jobs()["ui"]
        shards = re.search(r"^        shard: \[(.+)\]$", ui, re.M).group(1).split(", ")
        total = len(shards)
        self.assertEqual(shards, [str(i) for i in range(1, total + 1)])
        self.assertIn("fail-fast: false", ui)
        self.assertIn(f"SHARD: ${{{{ matrix.shard }}}}/{total}\n", ui)
        self.assertIn(f"/{total}\n", re.search(r"^    name: (.+)$", ui, re.M).group(0) + "\n")
        self.assertIn('npm run test:ui -- --shard="$SHARD" --reporter=list,blob', ui)
        self.assertIn("name: browser-ui-shard-${{ matrix.shard }}", ui)
        merge = step_script("ci.yml", "Merge the shard reports into one Playwright JSON report")
        self.assertIn(f"for shard in {' '.join(shards)}; do", merge)

    def test_one_merged_report_keeps_the_artifact_the_gate_and_release_read(self):
        jobs = ci_jobs()
        report = jobs["ui-report"]
        self.assertIn("    needs: [ui]\n", report)
        self.assertIn("    if: ${{ !cancelled() }}\n", report)
        self.assertIn("name: browser-ui-report\n", report)
        self.assertIn("apps/web/test-results/ui-report.json\n", report)
        self.assertNotIn("browser-ui-report", jobs["ui"])
        self.assertIn('--ui-json "$RUNNER_TEMP/reports/browser-ui-report/ui-report.json"', jobs["gate"])
        self.assertEqual(step_script("ci.yml", "Require every shard to succeed").strip().splitlines()[-1],
                         'test "$SHARDS" = success')
        self.assertIn("SHARDS: ${{ needs.ui.result }}", report)

    def test_the_merge_step_refuses_a_missing_shard(self):
        script = step_script("ci.yml", "Merge the shard reports into one Playwright JSON report")
        total = len(re.search(r"^        shard: \[(.+)\]$", ci_jobs()["ui"], re.M).group(1).split(", "))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bin").mkdir()
            # Stand-ins: npx records the blobs it is given and writes a report; jq is not needed for the check.
            (tmp / "bin" / "npx").write_text('#!/bin/sh\nls "$5" > "$RUNNER_TEMP/merged-blobs"\n'
                                             'echo \'{"stats": {}}\' > "$PLAYWRIGHT_JSON_OUTPUT_NAME"\n')
            (tmp / "bin" / "jq").write_text("#!/bin/sh\nexit 0\n")
            for name in ("npx", "jq"):
                (tmp / "bin" / name).chmod(0o755)
            web = tmp / "apps" / "web"
            web.mkdir(parents=True)
            env = {**os.environ, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp)}
            for shard in range(1, total + 1):
                blob = tmp / "shards" / f"browser-ui-shard-{shard}" / "blob-report"
                blob.mkdir(parents=True)
                if shard != total:
                    (blob / f"report-{shard}.zip").write_text("zip")
            run = lambda: subprocess.run(["bash", "-eo", "pipefail", "-c", script], cwd=web, env=env,  # noqa: E731
                                         stdin=subprocess.DEVNULL, capture_output=True, text=True)
            missing = run()
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn(f"shard {total} uploaded no blob report", missing.stdout)
            (tmp / "shards" / f"browser-ui-shard-{total}" / "blob-report" / f"report-{total}.zip").write_text("zip")
            (tmp / "shards" / "browser-ui-shard-1" / "ui" / "trace").mkdir(parents=True)
            complete = run()
            self.assertEqual(complete.returncode, 0, complete.stderr)
            self.assertEqual((tmp / "merged-blobs").read_text().split(),
                             [f"report-{i}.zip" for i in range(1, total + 1)])
            self.assertTrue((web / "test-results" / "ui-report.json").exists())
            self.assertTrue((web / "test-results" / "ui" / "shard-1" / "trace").is_dir())

    def test_dependency_audit_job(self):
        audit = ci_jobs()["audit"]
        self.assertIn("    name: Dependency audit\n", audit)
        self.assertIn("npm ci --no-audit --no-fund", audit)
        npm = step_script("ci.yml", "Audit web production dependencies (npm audit)")
        self.assertIn("npm audit --omit=dev --json", npm)
        self.assertIn("dependency_audit.py npm", npm)
        pip = step_script("ci.yml", "Audit API locked dependencies (pip-audit)")
        self.assertIn("uv export --frozen --no-dev", pip)
        self.assertIn('pip-audit==${PIP_AUDIT_VERSION}', pip)
        self.assertIn("--require-hashes", pip)
        self.assertIn("dependency_audit.py python", pip)
        self.assertRegex((WORKFLOWS / "ci.yml").read_text(), r'\n  PIP_AUDIT_VERSION: "\d+\.\d+\.\d+"\n')


class OnlyGitHubHostedCi(unittest.TestCase):
    def test_ci_is_the_only_workflow_and_every_action_is_pinned(self):
        self.assertEqual(sorted(p.name for p in WORKFLOWS.glob("*.yml")), ["ci.yml"])
        for workflow in WORKFLOWS.glob("*.yml"):
            text = workflow.read_text()
            self.assertIn("\npermissions: {}\n", text)
            self.assertEqual(set(re.findall(r"runs-on: (.+)", text)), {"ubuntu-latest"}, workflow.name)
            self.assertIsNone(re.search(r"secrets\.|vars\.|^\s+environment:", text, re.M), workflow.name)
            for uses in re.findall(r"uses: (\S+)", text):
                self.assertRegex(uses, r"@[0-9a-f]{40}$", f"{workflow.name}: {uses} is not pinned by SHA")


if __name__ == "__main__":
    unittest.main()
