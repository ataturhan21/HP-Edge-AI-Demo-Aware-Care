---
doc_id: ENG-08
title: Delivery workflow and ZGX Nano deployment runbook
status: implementation-handoff-not-runtime-verification
baseline: Product Master Document 2.0
prepared_on: 2026-10-14
owner: M12
requirement_ids: [R34, R37, R38, R40]
decision: ../decisions/ADR-010-delivery-workflow.md
---

# Delivery workflow and ZGX Nano deployment runbook

> [!WARNING]
> **Maintainers only.** The workflows here (`release.yml`, `deploy-nano.yml`, `deploy-fury.yml`) act on the
> maintainer's two demo devices through their self-hosted runners and approval gates. Never dispatch them to try the
> demo: a run waits in that device's deploy queue and blocks real deployments. To run Aware Care on your own ZGX Nano
> or Fury, run [`./demo.sh local`](../../README.md#run-it), which uses the same deploy
> tool on your device with images you build yourself.

This runbook covers how a change reaches the demo devices: pull request → CI → one manual
`scripts/release/release.sh` (a prerelease with linux/arm64 images, both deploy workflows, a smoke test, a short
release note, then the prerelease published) → rollback when needed. The decisions behind it are in
[ADR-010](../decisions/ADR-010-delivery-workflow.md) and [ADR-019](../decisions/ADR-019-lean-delivery.md) (lean
delivery). The device facts are in
[ENG-07](07-nano-zrt-operations.md). Deployment configuration is in
[`infra/deploy/demo-zgx-nano.json`](../../infra/deploy/demo-zgx-nano.json).

A successful deployment proves that the packaged synthetic flow runs on the device in the selected mode. It does
**not** verify any requirement, prove clinical readiness or prove local inference. Requirement statuses and
`NOT_EXECUTED` acceptance records change only through `evidence/README.md`.

## 1. Pieces

| Piece | Path | Trigger | Runs on |
|---|---|---|---|
| PR template | `.github/pull_request_template.md` | Every PR | n/a |
| CI | `.github/workflows/ci.yml` | PR to `main`, push to `main`, merge queue (`merge_group`) | `ubuntu-latest` (or `vars.AWARE_CARE_CI_RUNNER`) |
| Release | `.github/workflows/release.yml` | Manual, from `main` | Verify and draft jobs on `ubuntu-latest`; build on `ubuntu-24.04-arm` (or `vars.AWARE_CARE_ARM64_RUNNER`) |
| Deploy | `.github/workflows/deploy-nano.yml`, `deploy-fury.yml` (ADR-018) | Manual, at a release tag | Resolve job on `ubuntu-latest`; deploy job on the device's self-hosted runner (`aware-care-nano`, `aware-care-fury`) |
| Wiki | `.github/workflows/wiki.yml`, `scripts/publish_wiki.py` | Push to `main` that changes `docs/wiki/` or its publisher; manual | `ubuntu-latest` (secret `WIKI_PUSH_TOKEN`) |
| Images | `infra/deploy/{api,web}.Dockerfile`, `build_images.sh` | Release build, CI smoke test | |
| Device tool | `infra/deploy/nano_deploy.py` (`deploy`, `rollback`, `status`, `presenter-key`; `--config` selects the device) | Deploy job, operator | Nano, Fury |
| Flow check | `infra/deploy/flow_check.py` | After every start and rollback | Nano, Fury |
| Manifest/summary | `infra/deploy/release_manifest.py` | CI gate, release, deploy | |

CI jobs: workflow lint (actionlint + shellcheck), specification traceability,
contracts, backend acceptance (mock, JUnit report), generated API types match `openapi.json`, web typecheck and
build, browser UI tests (mock; since #509 eight parallel shards, `--shard=i/8`, whose blob reports the
`ui-report` job merges into the one Playwright JSON report, artifact `browser-ui-report`), package smoke test
(builds both images, deploys them with `nano_deploy.py` on ports 18100/18180 and runs the flow check), dependency
audit (#369: `npm audit` of the web production dependencies, high or critical fail; `pip-audit` of the API's
locked requirements, any finding fails; dated exceptions only in `.audit-ignore.json`), the Wiki source and tooling tests (`docs`: Wiki lint and
`tests/tooling`), and a single **CI gate**
job that requires every other job to succeed. The gate summary lists executed counts next to the registry statuses.

## 2. Runtime shape on the Nano

| Item | Value |
|---|---|
| Containers | `aware-care-demo-api`, `aware-care-demo-web` (`*-previous` only during a deployment) |
| Network | `--network host`; API `127.0.0.1:8100`, web gateway `127.0.0.1:8180`; no published ports |
| ZRT | Host loopback `127.0.0.1:8080/v1`, reached directly because container loopback is host loopback. Not managed here. |
| Browser | One tunnel for patients and presenters (#487): `ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 NANO_USER@NANO_HOST` (`<ssh-port>`: the device's SSH port, default 22), then open http://127.0.0.1:18180 (127.0.0.1, not localhost) and choose Patient or Presenter on its home page |
| Allowed origin | `http://127.0.0.1:18180` exactly (`network.browser_origin`), for both roles; `localhost` or another local port gets 403 |
| Hardening | read-only root, tmpfs `/tmp`, `--cap-drop ALL`, `no-new-privileges`, non-root, no GPU devices, `--restart unless-stopped` |
| Data root | `vars.AWARE_CARE_DATA_ROOT` (Fury: `vars.AWARE_CARE_FURY_DATA_ROOT`) or `~/.local/share/aware-care-demo` (of the runner user) |
| Data | `data/mock/`, `data/local/` (SQLite, uploads, exports; synthetic only) |
| State | `state/current.json`, `state/previous.json` |
| Evidence | `evidence/<timestamp>-<tag>-<action>.json` |
| Secrets | Optional `secrets/api.env`, mode 0600, passed with `--env-file`. The app currently reads no credential. |
| Lock | `deploy.lock` (`flock`) |

The development servers (8000/5173) and the browser-test stack (18000/15174; one gateway port since #487) keep their ports and can run
alongside the deployment.

## 3. One-time setup (owner: infrastructure lead)

None of these steps were performed by CHG-DEV-CI-001. Each needs the access noted.

**State on 2026-10-14:** done: 1 (Project), 3 (runner registered, not yet a service), 4, 5 (`ubuntu-24.04-arm` confirmed; no variable needed), 6 (GHCR verified with `v0.1.0-demo.1`), 7 (repository ruleset "Require CI gate on main"). Later the same day, the device owner completed 2 (Docker daemon proxy) and the runner service in 3. The first mock deployment of `v0.1.0-demo.1` then succeeded (a workflow run). All steps in this section are done.

1. **GitHub Project.** Refresh the CLI token with the Project scope, then add issues to the configured Project:
   ```bash
   gh auth refresh -h github.com -s project
   gh project list --owner <owner>
   gh project item-add <PROJECT_NUMBER> --owner <owner> --url #3
   ```
2. **Docker daemon proxy on the Nano.** The daemon cannot reach `ghcr.io` (ADR-010 #16), but the shell reaches it
   through the site proxy. Add a systemd drop-in with the site's proxy values. This needs `sudo`, and restarting
   Docker restarts its containers:
   ```bash
   sudo mkdir -p /etc/systemd/system/docker.service.d
   printf '[Service]\nEnvironment="HTTP_PROXY=%s" "HTTPS_PROXY=%s" "NO_PROXY=localhost,127.0.0.1"\n' \
     "$HTTPS_PROXY" "$HTTPS_PROXY" | sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf
   sudo systemctl daemon-reload && sudo systemctl restart docker
   docker pull --quiet ghcr.io/astral-sh/uv:0.13.0   # confirms registry access
   ```
3. **Self-hosted runner on the Nano.** Repository → Settings → Actions → Runners → *New self-hosted runner*
   (Linux, ARM64). Run it as a dedicated non-root user that belongs to the `docker` group, add the label
   `aware-care-nano`, give the runner the site proxy (its `.env` file), and install it as a service with
   `sudo ./svc.sh install <user>`. This adds a service to the device, so it needs an explicit decision under
   CLAUDE.md. If you use other labels, set them:
   ```bash
   gh variable set AWARE_CARE_NANO_RUNNER_LABELS --repo <owner>/<repo> \
     --body '["self-hosted","linux","ARM64","aware-care-nano"]'
   ```
4. **Environment `demo-zgx-nano`.** It does not exist yet. A workflow run would create it unprotected, so create
   it first with a reviewer and tag-only deployments:
   ```bash
   R=<owner>/<repo>
   REVIEWER_ID=$(gh api users/<github-login> --jq .id)
   gh api -X PUT repos/$R/environments/demo-zgx-nano --input - <<EOF
   {"reviewers":[{"type":"User","id":$REVIEWER_ID}],
    "deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
   EOF
   gh api -X POST repos/$R/environments/demo-zgx-nano/deployment-branch-policies -f name='v*' -f type=tag
   ```
   Optional environment variables: `AWARE_CARE_MODEL_ID` (local mode) and `AWARE_CARE_DATA_ROOT`:
   ```bash
   gh variable set AWARE_CARE_MODEL_ID --env demo-zgx-nano --repo $R --body '<ZRT served model ID>'
   ```
5. **arm64 build runner.** Confirm that GitHub-hosted `ubuntu-24.04-arm` is enabled for this private repository in
   `<owner>`. If it is not, point the build at an approved arm64 runner (for example the Nano runner label):
   ```bash
   gh variable set AWARE_CARE_ARM64_RUNNER --repo <owner>/<repo> --body aware-care-nano
   ```
   If `ubuntu-latest` is not permitted for CI either, set `AWARE_CARE_CI_RUNNER` to an approved x64 or arm64 label.
6. **GHCR packages.** After the first release, open both packages under the organization's Packages tab and
   confirm that each is linked to this repository and inherits its access, so the deploy job's `packages: read`
   token can pull. If organization policy blocks package creation by `GITHUB_TOKEN`, the release build job fails
   at the push step.
7. **Required check.** Make **CI gate** a required status check for `main`. Branch rules come from the organization
   ruleset "Require PR before merging", so an organization admin must add it or approve a repository ruleset.

## 4. Releasing (one command, ADR-019)

Release per batch or milestone, not per bug, from a machine with the GitHub CLI logged in, SSH key access to the
Fury, and `apps/web/node_modules` with Playwright's Chromium (the Nano itself is the usual place):
```bash
scripts/release/release.sh 0.16.0-demo.1        # version without the leading v; --dry-run prints the plan
scripts/release/release.sh --only nano 0.16.0-demo.2   # one device on purpose
scripts/release/release.sh --deploy-only 0.16.0-demo.2  # finish an existing tag at its own commit (#621)
```
1. **CI:** `main`'s HEAD must have a green push CI run (`dispatch_release.sh` waits for a running one).
2. **Build:** `release.yml` makes the linux/arm64 images, tag `v<version>` and a **draft prerelease** with digests.
3. **Deploy:** each device is checked first and **skipped** with a reason when it is not ready (#544): its self-hosted
   runner (`aware-care-<device>-*`) is offline, another deploy run of it is queued or in progress, or its SSH host does
   not answer (`fury: skipped, runner offline (...)`, `fury: skipped, no route to host`). The others go on:
   `deploy-fury.yml` and `deploy-nano.yml` run at the same time, in local mode with each device's model from its
   manifest (`dispatch_deploy.sh` approves each run at its environment; an approval GitHub refuses is retried up to
   5 times with a short backoff while the run still waits there, then the run is cancelled with GitHub's HTTP status
   and message and the environment it waited at, #620). Each workflow is dispatched through GitHub's REST API, whose
   reply names the run that dispatch created; only that run is approved, polled, cancelled and downloaded, never
   another dispatch's (#584, also for `release.yml`). A reply without a run ID stops that device before anything is
   approved; its run then waits at the environment until you approve or cancel it in GitHub Actions. Every wait has
   a deadline: a run still queued after 5 minutes (`AWARE_CARE_DEPLOY_QUEUE_TIMEOUT`, seconds) or unfinished after 15
   (`AWARE_CARE_DEPLOY_TIMEOUT`) is cancelled and reported with its cause: still waiting for approval at the
   environment, queued for a busy device runner, or the device runner offline. A failed check rolls that device back
   by itself (§5.6).
4. **Smoke (about 3 minutes per device):** through the browser address `127.0.0.1:18180` (an SSH tunnel for the Fury,
   a loopback forwarder on the Nano): readiness, one patient consultation from the home page's Patient choice to
   the device AI's guidance, and all three presenter Quick flows (Guidance, Self-care, Urgent), each of which must
   show its result (`tests/devices/smoke.spec.ts`, #538). The note lists each flow's outcome and time. Each smoke
   stops after `AWARE_CARE_SMOKE_TIMEOUT` seconds (720); the local device's smoke holds the model lock (§4.1).
5. **Note:** the GitHub release body becomes the short release note: the PRs since the previous release, the deploy
   result per device, the smoke results. Results stay in `~/aware-care-release/<tag>/` (`AWARE_CARE_RELEASE_DIR`), outside Git.
6. **Publish (#600):** after a successful run (every selected device deployed and passed its smoke) `release.sh`
   publishes the draft, still marked **prerelease**. After a skipped or failed device it stays a draft and the output
   prints the `gh release edit <tag> --draft=false --prerelease` to run once the device has it. Releases up to
   `v0.16.4-demo.1` stay drafts; `v0.17.0-demo.1` to `v0.18.2-demo.1` were published on 2026-10-26.

**Finishing a release whose tag already exists (#621):** when an earlier run built `v<version>` but did not deploy,
smoke or publish it, run `release.sh <version>` again: it sees the tag, skips steps 1-2 (`release.yml` would refuse an
existing tag) and does steps 3-6. It resumes only when the tag points at `main`'s HEAD, that commit has a successful
push CI run, and the release run named in the tag's `release-manifest.json` succeeded for this tag and commit. When
`main` has moved on since, `release.sh --deploy-only <version>` does the same for the tag's own commit (it refuses when
the tag does not exist). Otherwise it stops with the reason and deploys nothing: a tag at another commit, a commit
without a green push CI run, or no successful release run (no manifest, or its run failed). `--dry-run` runs these
checks too, read-only. No more deploying by hand with `dispatch_deploy.sh`.

The devices: the Fury over SSH (`AWARE_CARE_FURY_SSH`); the Nano is the machine `release.sh` runs on unless
`AWARE_CARE_NANO_SSH` names one. `AWARE_CARE_FURY_MODEL` / `AWARE_CARE_NANO_MODEL` override the manifests' model IDs
(`scripts/release/release.sh --help`).

The exit status is 0 only when every selected device deployed and passed its smoke; a skipped or failed device makes
it 1, but the tag is made and the note names each device's result. Re-run only the smoke, read-only, against
what the devices run now: `scripts/release/release.sh --smoke-only [fury|nano|both]`. Port 18180 must be free (close
other tunnels first). There is no release PR, evidence folder, repeated suite run or routine backup (the data is
synthetic); `scripts/release/backup.sh <label>` stays available by hand.

### 4.1 One AI job per device model

The device model serves one request at a time, so parallel AI jobs only slow each other down. Every AI job takes
the device's model lock (`flock` on `/tmp/aware-care-model.lock`, one file for all users of the device;
`AWARE_CARE_MODEL_LOCK` overrides it): `scripts/ai_regression/run.sh` (the Fury's cases on the Fury),
`./demo.sh check-model`, the release smoke of the local device, a local-mode deploy's checks (`nano_deploy.py`, so
`./demo.sh local`/`setup` and both deploy workflows; it waits at most 300 s before anything changes, #578), and any
other harness through
`scripts/dev/with_model_lock.sh <command>`. A second job prints `waiting for the model (another AI job is running:
<pid> <command>) <n> s` and gives up after `AWARE_CARE_MODEL_LOCK_WAIT` seconds (3600; 1800 for the release smoke).
Killing the wrapper (SIGTERM, SIGINT, SIGHUP) stops its command's whole process group, and the lock is free only
once the command has exited; a SIGKILLed wrapper leaves the lock with its still-running command (#566).

The pieces can also run alone (maintainer, for the two demo devices only): `gh workflow run release.yml --ref main -f version=<version> [-f commit=<sha>]`,
`gh workflow run deploy-<device>.yml --ref v<version> -f mode=local -f model_id=<ZRT served model ID>` (approve it in
the environment), `scripts/release/host_checks.sh` on a device for read-only host facts, and
`scripts/release/deployed_checks.sh` for the larger probe set (journeys, written emergencies, RF20, non-health text).

Local readiness is `ready` only while the enabled reviewed pathway is active and ZRT serves the configured model;
otherwise the deployment fails and restores the previous deployment (`unavailable`: no active pathway or model ID;
`degraded`: ZRT does not serve the model). The deploy flow check requires a non-mock result in local mode, and the
presenter check verifies presenter access, the scenario handoff and the capabilities the release declares
(`local-scenarios`, `quick-demos`, `quick-flows`; ADR-016).

**On the device** (from a checkout of the deployed tag, as the runner user):
```bash
python3 infra/deploy/nano_deploy.py status
python3 infra/deploy/nano_deploy.py --data-root ~/.local/share/aware-care-demo status
```

## 5. What a deployment does

1. **Resolve:** reads the annotated tag, checks the tag targets the dispatched commit, extracts the manifest,
   requires digest-pinned linux/arm64 packages, and requires `mode` to be exactly `mock` or `local`.
2. **Preflight** (nothing changes yet): host is aarch64, Docker is available, images pull by digest and are arm64,
   each image's `org.opencontainers.image.revision` label equals the release commit (#297), and
   ports 8100/8180 are free or held by this deployment. In local mode it also checks that the model ID is listed
   by `GET 127.0.0.1:8080/v1/models`. Mock mode never contacts ZRT.
3. **Switch:** the running containers are stopped and kept as `*-previous`, and the new ones start with the
   settings in §2.
4. **Readiness:** `GET http://127.0.0.1:8180/api/v1/health/ready` through the gateway must answer `ready`
   within 60 s. This check, the flow and presenter checks and `status` use the gateway's bind address
   (`network.bind_host`; `http://[::1]:8180` for `::1`, #587) and never an HTTP proxy from the environment.
5. **Flow check:** one synthetic guest journey through the gateway: shell and deep route, session, case, every
   issued question (10-slot cap), review, guidance job, guidance, then session deletion (202). In mock mode the
   guidance must come from `mock-fixture-adapter-1`; in local mode a mock-labeled result fails.
6. **Keep or roll back:** on success the state files are updated first, then the parked containers are removed.
   The two state files change together or not at all (#591): when they cannot be written (a full disk, a refused
   write) the deployment counts as failed and is rolled back as below, and the files still name the restored release.
   On failure the parked deployment is restored and re-checked, the evidence says `ROLLED_BACK` (or
   `ROLLBACK_FAILED`), and the run fails. With nothing to restore, the failed containers are removed and nothing is left running.
7. **Evidence:** written to the device and uploaded as a workflow artifact; the job summary shows the outcome.

## 6. Rollback

- **Automatic:** part of every failed deployment (§5.6).
- **Preferred manual path:** redeploy the previous release tag through the workflow, which records evidence. Take
  the tag, mode and model from the device's `state/previous.json`: both devices run in **local** mode, and
  dispatching `mode=mock` would switch the demo to synthetic answers (#300).
  ```bash
  # On the device (default data root): the rollback target's tag, mode and model ID.
  jq -r '"tag=\(.release_tag) mode=\(.mode) model_id=\(.model_id // "")"' \
    ~/.local/share/aware-care-demo/state/previous.json
  # Then dispatch exactly those values (deploy-fury.yml on the Fury); omit -f model_id in mock mode.
  gh workflow run deploy-nano.yml --repo <owner>/<repo> --ref <tag> \
    -f mode=<mode> -f model_id=<model_id>
  ```
- **On the device** (for example when GitHub is unreachable): redeploys `state/previous.json` by digest, with the
  same checks. Run it from a full checkout of the running release, not just `infra/deploy`: it also reinstalls the
  power sampler from `infra/telemetry`. GHCR credentials exist only inside workflow jobs, so add `--no-pull` when the
  previous images are already on the device; they normally are, because each deployment pulls its own.
  ```bash
  python3 infra/deploy/nano_deploy.py --config infra/deploy/<device>.json rollback --no-pull
  ```
- **Rollback target:** since #170, redeploying the release that already runs keeps `state/previous.json`. Before
  that, a same-release redeploy replaced the target with itself, leaving nothing different to roll back to. Since
  #300, a successful rollback (the `rollback` command, or a deployment of the release `state/previous.json` names)
  clears `state/previous.json` instead of recording the release it rolled back from, so a second rollback cannot
  redeploy the bad release; it reports "no previous deployment is recorded". The evidence names the replaced
  release under `rolled_back_from`.
- **Cancelled or timed-out deployment:** since #294, a cancel, a job timeout (SIGINT/SIGTERM from the runner) or any
  unexpected error after the switch started restores whatever was parked. After a signal the restored containers are
  not re-checked (the runner allows only seconds before it kills the job); the evidence says `RESTORED_UNCHECKED`, so
  check `nano_deploy.py status`. The deploy jobs' 40-minute timeout is above the tool's worst case (about 29 minutes,
  documented next to `LOCK_WAIT_SECONDS` in `infra/deploy/nano_deploy.py`).
- **A rollback to a release before #152** also reinstalls that release's power sampler, without the private file
  mode. The next deployment of a current release restores it.
- **Emergency stop:** `docker rm -f aware-care-demo-api aware-care-demo-web`. Data and state stay on disk; the next
  deployment starts cleanly.
- **Data compatibility:** the SQLite schema is created idempotently by the API. If a rollback meets an incompatible
  synthetic database, stop the containers, move `data/<mode>` aside, and redeploy. All data is synthetic.

## 7. Reset and troubleshooting

| Symptom | Check |
|---|---|
| Pull fails with `context deadline exceeded` | Docker daemon proxy (§3.2) |
| `loopback port(s) [...] are in use by another process` | `ss -ltnp \| grep -E ':(8100\|8180)'`; stop the other process. Port values are in `demo-zgx-nano.json`. |
| Readiness `unavailable` in local mode | The release has no active reviewed pathway (before `v0.5.0`, or the enabled pathway expired on 2027-10-15), or no model ID is set. The deployment rolls back. |
| Readiness `degraded` in local mode | ZRT does not serve the configured model: `curl -s http://127.0.0.1:8080/v1/models`. |
| `configured model <id> is not served by ZRT` | `curl -s http://127.0.0.1:8080/v1/models`. Serving models is a ZRT task outside this workflow. |
| Browser gets 403 | The tunnel origin must be exactly `http://127.0.0.1:18180`, for patients and presenters alike (#487), not `localhost`. Another address: set `network.browser_origin` in `demo-zgx-*.json` and redeploy through the workflow |
| Container exits | `docker logs aware-care-demo-api` (content-free operational logs only) |
| Full synthetic reset | `docker rm -f aware-care-demo-api aware-care-demo-web`, delete `<data_root>/data/mock`, redeploy |

## 8. Recovery

The deploy workflows roll back by themselves; a manual rollback is a deploy-workflow run at the previous tag (§6).
Recovery exercises: 2026-10-14 (a workflow run, about 63 s unavailable) and on both devices on 2026-10-18 (#170:
automatic rollback about 62 s, workflow rollback, on-device rollback on the Fury, model cold start, boot readiness;
records in `evidence/operations/2026-10-18-recovery-exercise/`, including the boot-check installer). Repeat one only
after a change to `nano_deploy.py`, by deploying a deliberately broken candidate through the workflow.

**Post-boot check (installed once):** every deployment copies `infra/deploy/boot_check.py` to
`<data_root>/ops/boot_check.py` and records whether the user crontab has its `@reboot` line
(`@reboot /usr/bin/python3 <data_root>/ops/boot_check.py >> <data_root>/ops/boot-check.log 2>&1`, added by the
installer above). After each boot it writes `<data_root>/evidence/<UTC time>-boot-check.json` and changes nothing.

(§9, the recovery-exercise procedure, was removed by ADR-019; the section numbers below are kept because other
records cite them.)

## 10. Presenter access (ADR-005 option A, amended by #487)

Patients and presenters use **one address**: the gateway on `127.0.0.1:8180`, forwarded as 18180. Its home page offers
two choices, Patient and Presenter. The presenter tools are its `/presenter/...` pages, which call the presenter API
`/presenter-api/...`; the gateway signs those requests. Patient pages call `/api/...`, where the gateway removes any
presenter header. Since #487 there is no presenter port (8181) any more.

Presenter access exists only when `<data_root>/secrets/presenter.key` exists. On the Nano, as the runner user:
```bash
python3 infra/deploy/nano_deploy.py presenter-key            # creates the key (mode 600, value never shown)
python3 infra/deploy/nano_deploy.py presenter-key --rotate   # replaces it; redeploy afterwards
```
The next deployment enables the presenter path, and the deployment check also proves:
- a presenter session and runtime read work through `/presenter-api/` (which identifies itself with
  `X-AwareCare-Gateway: presenter`);
- a forged assertion sent to `/api/` yields `403 PRESENTER_REQUIRED`.

**Loopback only.** The deploy tool refuses a deployment that has a presenter key while the gateway binds a non-loopback
address (`network.bind_host` or `--bind-host`). It refuses before it pulls or stops anything. The gateway container
refuses the same on its own. Presenter access must not reach a network until ADR-005's TLS / mTLS decision is made. An
older configuration's `presenter_port` and `presenter_origin` (and `--presenter-port`, `--presenter-origin`) are read
and ignored; the deployment evidence names them.

To present, open the one tunnel and choose **Presenter** on the home page (or open `/presenter/scenarios` directly):
```bash
ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<nano-host>   # then http://127.0.0.1:18180 (not localhost)
```
One browser is enough. Open the presenter tools in one tab; the patient tab opens `/app/...` on the same address as a
patient. The two roles use separate cookies (ADR-005 implementation notes). On O03, **Load scenario** hands the patient
tab a synthetic demo session (open History there); **Reset demo** removes it and keeps the presenter session. A failed
reset blocks new demos until **Retry reset** succeeds. After a deployment, the presenter check loads and resets a
scenario this way (when the release declares `scenario-handoff`).
Anyone who can log in to the Nano can forward this port; that is the accepted boundary of option A. To disable
presenter access, delete the key file and redeploy. The presenter tools then say that presenter access is not enabled.

## 10b. GPU power sampler for the telemetry page (W06, ADR-017, #122)
The telemetry page measures the GPU energy of each AI call from `nvidia-smi` power readings. A small read-only host
script, `infra/telemetry/power_sampler.py`, takes one reading per second and writes hourly files to
`<data_root>/data/local/power/` (48-hour retention). The API reads those files through its existing data mount. The
script only reads the GPU's reported power and changes no ZRT, driver, CUDA or GPU setting.

- **Installed by each deployment:** a successful `nano_deploy.py` copies the release's script to
  `<data_root>/telemetry/power_sampler.py`. The deployment record notes whether the crontab keeper exists
  (`power_sampler.cron_keeper`). The deployment never edits the crontab.
- **Kept running (installed once):** add this user crontab line. `flock` keeps a single sampler; cron restarts it
  within a minute after a reboot or an exit.
  ```bash
  DR=$HOME/.local/share/aware-care-demo
  (crontab -l; echo "* * * * * /usr/bin/flock -n $DR/telemetry/sampler.lock /usr/bin/python3 $DR/telemetry/power_sampler.py --out $DR/data/local/power >> $DR/telemetry/sampler.log 2>&1") | crontab -
  ```
- **Check it:** `tail -2 $DR/data/local/power/$(date -u +%Y%m%dT%H).csv` shows `epoch_ms,watts` lines from the last
  seconds. The telemetry page shows "Power sampler active".
- **Without it:** energy and the electricity cost show "Not measured". Nothing else is affected.
- **Remove it:** delete the line with `crontab -e`, and remove `$DR/telemetry` and `$DR/data/local/power`.

## 10c. The second device: HP ZGX Fury (ADR-018, #142)
The Fury (GB300) is deployment target `demo-zgx-fury`. It runs the same release images as the Nano and is deployed
with `deploy-fury.yml`. Its configuration, `infra/deploy/demo-zgx-fury.json`, names the device and selects the API's
Fury files (`infra/fury/`). Everything else in this runbook applies with "Fury" for "Nano"; its repository variables are
`AWARE_CARE_FURY_MODEL_ID`, `AWARE_CARE_FURY_DATA_ROOT` and `AWARE_CARE_FURY_RUNNER_LABELS` (the Nano's:
`AWARE_CARE_MODEL_ID`, `AWARE_CARE_DATA_ROOT`, `AWARE_CARE_NANO_RUNNER_LABELS`). Set up on 2026-10-17/18
for user `<user>`; no sudo is available on that host.

- **Runner.**
  - **Installed:** `<runner-name>`, labels `self-hosted, Linux, ARM64, aware-care-fury`, version 2.338.0 (the
    download sha256 was checked against the release notes). It lives in `~/actions-runner/aware-care-fury`, with the
    host proxy in its `.env`.
  - **Service:** the user unit `actions-runner-aware-care-fury.service`, a user unit because `svc.sh install` needs
    root. It runs without a login session because lingering is enabled (#139).
  - **Registration:** the one-time token came from `gh api -X POST repos/<repo>/actions/runners/registration-token`
    and was piped straight into `config.sh`, never written to a file or log.
  - **Check it:** `systemctl --user status actions-runner-aware-care-fury`; GitHub lists the runner online.
- **Environment.** GitHub environment `demo-zgx-fury`: the maintainer as required reviewer, `v*` tags only, as for
  the Nano.
- **ZRT model (outside app deployment).**
  - **The unit:** `aware-care-zrt-model.service` (`infra/fury/zrt/`) runs `serve-model.sh` at boot, which serves
    `qwen3.8-flash-next-fp8` with the qualified settings.
  - **CUDA on PATH:** the script puts the installed CUDA 13.2 first on PATH for that command only. The distribution's
    CUDA 12.0 `nvcc` cannot build sm_103a kernels.
  - **Install:** copy the two files as the unit's header says, then
    `systemctl --user enable --now aware-care-zrt-model.service`.
  - **Check it:** `curl -s http://127.0.0.1:8080/v1/models` lists the model.
  - **Unchanged:** no ZRT, CUDA or driver setting.
- **Presenter key.** Created with `nano_deploy.py presenter-key` (mode 600, never printed).
- **Private data folders (#152).** The Fury's umask is 002. Every deployment now makes the data root, `data/` and
  `data/<mode>` 0700, and the power sampler creates private folders and files. The permissions found on 2026-10-18
  were corrected by hand.
- **Cron lines.**
  - **Power sampler:** the same as section 10b.
  - **Weekly usage collector (`scripts/monitoring.py collect`):** it copies the reviewed `scripts/monitoring.py` from the runner's
    checkout of the deployed release (`~/actions-runner/aware-care-fury/_work/…/scripts/monitoring.py`), because the
    Fury has no credentialed clone to fetch `origin/main`.
- **Tunnel.** `ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 FURY_USER@FURY_HOST`, then http://127.0.0.1:18180 (#487: one
  port for patients and presenters). Use the same local port as for the Nano, so the allowed origin matches. Don't run
  both tunnels at once.
- **Deploy** (maintainer; `scripts/release/release.sh` normally does this):
  - `gh workflow run deploy-fury.yml --ref v<version> -f mode=local -f model_id=qwen3.8-flash-next-fp8`
  - Approve it in the `demo-zgx-fury` environment. Never dispatch `mode=mock` to a demo device: it switches the demo to
    scripted answers (§6).

## 11. Boundaries

- No step changes ZRT, drivers, CUDA, GPU allocation, SSH, the dashboard, Ollama or Zabbix.
- No credential, runtime database, upload or health payload enters Git, an image, a log or an artifact.
- Publication of a release and every deployment are manual decisions; CI never releases or deploys.
- A green CI run, a release manifest or deployment evidence never moves a requirement to `verified` and never
  turns a `NOT_EXECUTED` acceptance record into a pass.
