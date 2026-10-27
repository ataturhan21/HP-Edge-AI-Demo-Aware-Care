# ADR-019: Lean delivery for a simple demo

Status: **Accepted 2026-10-23** by the maintainer: "it is a very simple demo, it should be much simpler … make it much
faster", with the rules below approved (issue #510). Supersedes ADR-011 (Wiki before closure) and the change-record,
spec-lock and evidence-folder parts of ADR-010 and `authority.md`. Affected IDs: R40. No requirement, screen, route,
operation or contract changes.

## Context
A typical fix took about 2 hours and a release about 2 hours. Most of it went to paperwork (work-log entries,
completion labels, change records), spec-lock merge conflicts, duplicate test runs and per-bug patch releases.

## Decision
1. **Issues and PRs.** One issue per real bug or feature; small fixes are batched. The PR body says `Fixes #N`, so
   the issue closes at merge. No per-issue work log (the PR body and git history are the record), no completion
   label, no device or deploy boxes left open for a release. the project board: Status only.
2. **Wiki.** `docs/wiki/` stays the reviewed source; `wiki.yml` publishes it on every push to `main`. It changes only
   when how-to docs change. The Issue Work Log pages are frozen history.
3. **Specification.** No `spec/lock.json` hash lock and no `CHG-*` records (archived in
   `spec/change-records-archive.md`). One screens file, `spec/screens.json`. `check_traceability.py` keeps the ID and
   mapping checks; new runtime files need no registration. ADRs only for real decisions (security model, model
   choice, boundaries).
4. **Tests.** Before a PR, run the specs of the touched screens or modules plus the backend; CI runs everything. A
   change to prompts, validation or repair runs the ~60-case regression set once per device before merge; it is
   advisory and never blocks a merge.
5. **Release.** One manual `scripts/release/release.sh <version>`: green push CI on `main`, build, both deploy
   workflows at once, a ~2-minute smoke per device, and a short release note as the GitHub release body; a successful
   run then publishes the prerelease (owner decision 2026-10-26, #600; amends ADR-010 #6). No release
   PR, evidence folder, repeated Nano suites, host or rollback-target checks, or backups (the data is synthetic).
   Release per batch or milestone, not per bug.
6. **Merging.** Merge small PRs as soon as CI is green, with a merge commit. A merge queue on `main` serialises
   merges when enabled.

7. **Safety process dropped** (maintainer, 2026-10-23: "there is no real world use case so ignore %99 of safety to
   make it much faster"): no hard gates such as a 100% urgent-recall gate, no clinical-reviewer sign-offs, no ADR
   amendments for safety changes, no new security-hardening work. The monthly clinician sample of ADR-003 item 7
   is no longer run. Existing presenter authorization, session code and the app's emergency routing stay as they are.

## Unchanged
The LLM stays on the device and no patient data leaves it (ADR-014); failed inference is never shown as success;
synthetic data only; credentials out of files; tests fail before a fix; no force-push; the maintainer's two demo devices
are deployed only through the deploy workflows, with their own rollback on failure (on any other machine,
`./demo.sh local` deploys by hand).
