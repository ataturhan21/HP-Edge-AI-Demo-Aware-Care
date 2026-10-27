# Contributing

The lean process for this simple demo ([ADR-019](<your-repo-url>/blob/main/spec/decisions/ADR-019-lean-delivery.md)).

## Rules

- **One issue per real bug or feature;** batch small fixes into one issue and one PR.
- **Branch** `<type>/<N>-<topic>` (`feat`, `fix`, `docs`, `chore`, `ci`, `test`).
- **Short PR** from the template: what, why, tests run, device check if AI-related. It says `Fixes #N`, and the issue closes when the PR merges.
- **No paperwork:** no work-log entry, no change record, no spec lock. ADRs only for real decisions. Update this Wiki only when how-to docs change.
- **Targeted tests before the PR:** `scripts/check_all.sh` (default `--changed`: type-check, contrast, contracts, the backend and only the browser specs related to the files changed against `origin/main`). CI runs everything. See [Testing](Testing).
- **AI changes** (prompts, validation, repair): the regression set (`scripts/ai_regression/run.sh both`) once per device before merge, with the result in the PR; advisory, it never blocks a merge. Wrap any other AI harness run in `scripts/dev/with_model_lock.sh <command>`. No clinical sign-offs or safety gates (ADR-019).
- **Merge as soon as CI is green,** with a merge commit. No squash, no rebase merge, never a force-push.
- **The maintainer's two demo devices changed only through deploy workflows** that are not part of this public repository ([Release and Deployment](Release-and-Deployment)). On any other machine, `./demo.sh local` deploys by hand.

## Tools in `scripts/dev/`

| Tool | What it does |
|---|---|
| `with_model_lock.sh <command...>` | Runs one AI job against the device model at a time (`flock` on `/tmp/aware-care-model.lock`, `AWARE_CARE_MODEL_LOCK` overrides it); a second job waits and names the holder. `run.sh`, `./demo.sh check-model` and a local-mode deploy take the lock themselves |
