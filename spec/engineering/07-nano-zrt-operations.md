---
doc_id: ENG-07
title: Nano and ZRT operations
status: implementation-handoff-not-runtime-verification
baseline: Product Master Document 2.0
observed_on: 2026-10-13
owner: M12
requirement_ids: [R23, R24, R26, R27, R34, R35, R36, R37, R38]
---

# Nano and ZRT operations

Aware Care runs on the HP ZGX Nano and, since ADR-018, the HP ZGX Fury (GB300). The user selected **ZRT as the sole real model-serving interface** on both. Sections 1–6 were written at handoff (2026-10-13) and keep that record. The application and local inference have since been implemented, qualified and deployed: see the **Update** notes, sections 8–9, `infra/model-manifest.json` and `infra/fury/model-manifest.json`.

The developer computer supplies the editor, SSH terminal, and browser. The Nano hosts the application and its local data and inference. A remote coding assistant is a separate service boundary; local application inference does not imply that an external coding tool keeps source-code context on the Nano.

## 1. Observed state and unresolved state

[Device inventory](../../infra/device-inventory.json) now records the read-only on-device observation of 22 October 2026 (#429), which replaced the user-supplied snapshot of 13 October 2026 that this section keeps. Preserve the distinction between observed and live values in the presenter UI and implementation reports.

| Confirmed observation | What it establishes |
|---|---|
| HP ZGX Nano; `aarch64`; Ubuntu 24.04.4; NVIDIA GB10 | Select native ARM64-compatible application dependencies. Do not use the earlier GB300 assumption. |
| NVIDIA driver 580.173.02; `nvidia-smi` CUDA 13.0 header | GPU detection and driver-reported CUDA capability. The installed CUDA Toolkit version is still unknown. |
| `Memory-Usage: Not Supported` | Expected memory-reporting limitation of this integrated GPU and shared-memory architecture; not evidence of missing memory. |
| 119 GiB shared memory; 113 GiB available at observation | Current host headroom, not an approved model memory allocation. Reserve capacity for OS, application, OCR, embeddings (*Future design: not built (ADR-004); local mode needs no corpus today*), and other workers. |
| NVMe display total 3.6T; available 2.9T | Current disk headroom. Do not remove existing files to prepare this handoff. |
| ZRT 0.39.0; snap revision `x3`; classic confinement; default mode `system` | Existing installed serving interface and observed mode. Do not reinstall or switch modes as a default step. |
| `zrt status`: no models served; no snap services listed | No served model was reported. Cached models and the ZRT service registry still need inspection. Snap services and ZRT model services are distinct. |
| ZRT help default `http://localhost:8080/v1` | A documented default only. No running model endpoint has been verified. |
| Node 24.21, npm 11.19, uv 0.13, managed Python 3.12.15, Git 2.43, tmux 3.4, rg 14.1, jq 1.7 | Observed tooling. Preserve the reported precision; do not invent patch versions. Claude installation remains unconfirmed. |

The idle GPU snapshot is not a load test. Model ID, immutable revision, tokenizer revision, quantization, context limit, generation settings, and actual runtime authentication remain unresolved. Their fields are `null` in [model-manifest.json](../../infra/model-manifest.json).

**Update 2026-10-15 (#26, ADR-002 accepted):** these are now resolved. The model is `Qwen/Qwen3.6-35B-A3B-FP8` at revision `95a723d08a9490559dae23d0cff1d9466213d989`, served by ZRT 0.39.0 (vLLM 0.30.0; ZRT 0.43.0, snap revision x4, since #75) as `qwen3.6-35b-a3b-fp8` with a 16,384-token context, FP8 and MTP. The proxy uses auth type none on 127.0.0.1. All fields, including the serving command, are in [model-manifest.json](../../infra/model-manifest.json). The qualification evidence is in `evidence/model-qualification/`. The observations above are kept as recorded on 2026-10-13.

The installed help includes `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` as an example. It is only a discovery candidate. No download, supported-device check, successful serving, quality evaluation, or performance result has been established for it.

## 2. Minimal next discovery on the Nano

Run these read-only commands in the existing Nano SSH session. The installed help is the authority for this exact ZRT version.

```bash
zrt version
zrt status
zrt models
zrt services
zrt serve --help
zrt config --help
```

The user-observed help documents `zrt models` as the alias for `zrt model list`, `zrt services` as the alias for `zrt service list`, and `zrt serve` as the background-start alias for `zrt service start`. **The command above is `zrt serve --help`; it does not request a service start.** Do not infer current service state from an alias description.

Capture the cached model list, service endpoints, effective configuration options, and version-specific authentication requirements. Do not paste credential values into project files or an AI conversation. If another help page is necessary, first use a subcommand actually displayed by this installation's help. Do not invent launch or configuration flags.

If process ownership or bindings need clarification, inspect them without changing services:

```bash
ss -ltnp
```

If another user's process details are omitted and access is available, `sudo ss -ltnp` is an optional read-only inspection. The user's latest output identifies the listener on 10050 as `zabbix_agent2`, PID 3919410. A wildcard binding alone does not establish Internet exposure.

No unconditional `sudo zrt setup`, authentication-disable option, driver/CUDA update, cache deletion, GPU-driver reload, service stop, or model launch belongs in this discovery step. ZRT may manage vLLM internally; that does not authorize a separately managed vLLM server. The existing Ollama installation is not selected and must not become a fallback.

## 3. Access and port boundaries

| Port | Status and use | Boundary |
|---|---|---|
| `<ssh-port>` (default 22) | Existing SSH; observed owners `sshd` / `systemd` | Use for remote editing and forwarding. |
| 11000 | Existing dashboard; displayed process name `dashboard-servi` | Preserve its loopback binding. It is not the model API. |
| 11434 | Existing Ollama listener; `ollama`, PID 2257 | Preserve; Aware Care does not call it. |
| 10050 | Existing Zabbix agent; `zabbix_agent2`, PID 3919410 | Preserve; do not repurpose or stop it. |
| 8080 | ZRT help default | Verify the effective endpoint before use; model API stays internal. |
| 8000 | Application API (development) | Loopback; the deployed API uses 8100 and the one gateway 8180 for patients and presenters (#487; `infra/deploy/demo-zgx-*.json`). |
| 5173 | Web development server (`./demo.sh mock`; the browser uses local port 15173) | Loopback during development; not a customer-demo production gateway. |

Connect from the developer computer using the actual Nano username and hostname/IP:

```bash
ssh -p <ssh-port> NANO_USER@NANO_HOST
```

After `./demo.sh mock` has started the development servers, open an SSH tunnel from your own computer (`demo.sh` prints it with your values filled in):

```bash
ssh -N -p <ssh-port> -L 15173:127.0.0.1:5173 NANO_USER@NANO_HOST
```

Then open exactly http://127.0.0.1:15173: the API accepts only that origin by default (`AWARECARE_ALLOWED_ORIGINS`), and the web server proxies `/api` to port 8000, so the API port needs no forwarding. Forwarding does not start either application server. Backend requests to ZRT originate on the Nano; no model-port forwarding is required. Select another **local** forwarding port if the developer computer already uses a listed port.

For a shared customer demo, expose only the built website and authorized application API through a trusted-network TLS gateway. Keep the model service, database, and files internal. [deployment.yaml](../../infra/deployment.yaml) is a design record with unresolved implementation, volume paths, and resource limits; it is not a Compose, Kubernetes, systemd, or ZRT configuration file.

## 4. Server configuration and exact mode behavior

[infra/.env.example](../../infra/.env.example) is the server-only configuration contract. `apps/api/app/config.py` loads and validates these mappings; an invalid value fails startup. The table covers the model and queue keys; the others (`AWARECARE_CONCERN_SCREEN_TIMEOUT_SECONDS`, `AWARECARE_ALLOWED_ORIGINS`, `AWARECARE_COOKIE_SECURE`, `AWARECARE_DATA_DIR`, `AWARECARE_PRESENTER_KEY_FILE`, `AWARECARE_TELEMETRY_PRICING`, `AWARECARE_MODEL_CATALOG`, `AWARECARE_APP_COMMIT`) are described with their defaults in the example file.

| Key | Required mapping and validation |
|---|---|
| `AWARECARE_MODE` | `mock` or `local`; reject other values. Default `mock`. |
| `AWARECARE_MODEL_PROVIDER` | Must be `zrt` in both modes. Mock mode bypasses the real provider entirely. |
| `AWARECARE_MODEL_BASE_URL` | Backend-only ZRT OpenAI-compatible base URL; example `http://127.0.0.1:8080/v1`. Resolve the actual service endpoint before local mode. |
| `AWARECARE_MODEL_ID` | Blank while unconfigured. In local mode, the model's short name (`qwen3.6-35b-a3b-fp8`); the API accepts it served under that label or its repository id, any case and revision, and sends requests under the ID ZRT lists (#528). |
| `AWARECARE_ALLOW_CLOUD_FALLBACK` | Must parse as boolean `false`; do not treat the string `"false"` as truthy. Reject an enabled value. |
| `AWARECARE_MODEL_MANIFEST` | Resolve the manifest path from the repository root or an explicit absolute deployment path. |
| `AWARECARE_DEVICE_INVENTORY` | Resolve the observed inventory path; do not present its timestamped values as live telemetry. |
| `AWARECARE_RETRIEVAL_MODE` | Default `offline`: local mode uses the versioned directory snapshot (versioned reviewed local evidence: *Future design: not built (ADR-004); local mode needs no corpus today*); mock mode uses its synthetic fixture pack. No live refresh or lookup. |
| `AWARECARE_ACTIVE_GENERATION_LIMIT` | Positive integer, baseline `1`, enforced across the application. |
| `AWARECARE_QUEUED_GENERATION_LIMIT` | Integer, baseline `3`, excluding the active job. |
| `AWARECARE_QUEUE_RETRY_AFTER_SECONDS` | Positive integer. Proposed initial value `5`; emit as `Retry-After` with saturation HTTP 429. This is not a promised completion time. |
| `AWARECARE_GENERATION_DEADLINE_SECONDS` | Baseline `60` for generation, including the single repair attempt. |
| `AWARECARE_SCHEMA_REPAIR_LIMIT` | Baseline `1`; a failed repair yields a failed job and the reviewed limited static fallback. |

Do not put these values into `VITE_*`, `NEXT_PUBLIC_*`, browser code, or a mobile bundle. In particular, the model URL, actual credentials, and internal service details must not be exposed by patient APIs. Authentication secret names and injection mechanics must follow the discovered ZRT contract; this handoff intentionally supplies no authentication-disable configuration.

`AWARECARE_RETRIEVAL_MODE=offline` describes the configured network policy. It is not a wire value for `RuntimeSnapshot.retrieval_mode`: that field uses the contract's `local`, `cached`, `connected`, or `unavailable` values according to observed retrieval state. Do not copy the configuration literal into an invalid API response. Similarly, `AWARECARE_MODEL_PROVIDER=zrt` selects the sole real serving interface; the runtime health interface may identify its active fixture adapter as `mock` when application mode is mock.

In **mock mode**, use explicit synthetic fixtures and mock job results. It must work without clinically reviewed pathways, a clinically reviewed corpus, or a running model. Simulate the defined scenarios and their UI states; do not perform arbitrary clinical assessment of user-entered text. Do not contact ZRT, Ollama, a cloud model, or a live provider directory. Show synthetic/demo labels throughout the relevant flows and presenter evidence. A successful mock test is evidence of simulated product behavior only.

In **local mode**, use the same application contracts and state machine with the ZRT adapter. Validate the pinned manifest, local endpoint, authentication contract, evidence versions, and readiness before routine guidance. If a dependency fails, show the specified limited/unavailable state. Do not silently return mock output, switch providers, or fall back to a cloud model.

The application admission queue implements one active generation job and three waiting jobs. A fifth distinct request receives HTTP 429 and `Retry-After`. Idempotent retries return the existing job instead of consuming new capacity. If multiple API processes or workers are introduced, coordinate the limit centrally; a per-process semaphore would incorrectly multiply capacity. Inference-engine queuing is not a substitute for application admission control. The concern screens of createCase, editCase and a written-urgency scenario load pass the same admission in a sibling screening lane (one active, three waiting, one per session; #397), so a single session cannot hold the runtime or the API's worker threads.

## 5. Model selection and local readiness milestone

Only after discovery, select a candidate supported by the installed ZRT/device combination and record its license and immutable identity. Inspect the installed command help before preparing its exact launch command. Model loading, unloading, and provider refresh are presenter operations outside active consultations.

Update the model manifest with the repository ID, actual served ID, immutable model revision, artifact digest where available, tokenizer identity/revision, quantization or explicit unquantized format, context limit, generation settings, and prompt hash. Keep unknown values null until verified; do not fill gaps from a model name. Discover the effective ZRT mode and cache location instead of assuming a path.

*Future design: not built (ADR-004); local mode needs no corpus today.* The evidence retrieval baseline is eight candidates, at most five selected passages, and a 6,000-token evidence budget. Fit system instructions, reviewed case facts, evidence, conversation, output, and any model-specific overhead within the selected model's context. This handoff does not choose a context length or reserve all 113 GiB of observed available memory for inference.

Implement `generate_json(task, prompt_version, input_snapshot, schema_id, timeout_s)`, `health()`, and `manifest()` in `apps/api/app/runtime/adapter.py`. Validate transport errors and schema failures as typed errors. A successful model response still requires the guidance schema, source/claim support checks, urgency consistency, and atomic ownership/state/input-revision/reviewed-revision/tombstone guards before publication. Keep model output hidden if these checks fail.

## 6. Health checks and evidence milestones

`GET /api/v1/health/ready` is the application's readiness endpoint (`getReadiness`, implemented) and returns readiness only. It must not expose model, device, credential, or internal URL details. Presenter runtime inspection is separately authorized. Readiness refers to the configured mode. The application UI, presenter runtime status, and verification reports must identify that mode clearly: mock readiness means **synthetic flow simulation ready**, never clinical readiness or real model readiness.

Both modes require application database access and writable temporary storage. Mock mode additionally requires its synthetic fixture pack and fixture adapter only. Local mode additionally requires the active reviewed clinical pathway (no corpus, ADR-004), a pinned model manifest, the verified ZRT endpoint/authentication contract, and actual model health. Do not block mock flow testing on unfinished clinical review or model selection.

| Milestone | Acceptance evidence | Current state |
|---|---|---|
| Device discovery | Timestamped hardware/software inventory | User-observed snapshot recorded. |
| ZRT discovery | Model cache, service endpoints, effective configuration and authentication identified | Done (2026-10-15; the Fury 2026-10-17, #137). |
| Mock application | Synthetic fixture pack plus all authorized simulated flows, error states, state guards, labels, and mock contracts work; no clinical corpus or model dependency | Implemented and tested. |
| Local model integration | Real pinned ZRT inference, context checks, typed failure handling, one repair maximum, and no provider fallback | Done: ADR-002 qualified per device (the Nano: Qwen3.6-35B-A3B-FP8; the Fury: Qwen3.8-Flash-Next-FP8). |
| Local application readiness | Database access, the active reviewed pathway, a served model, writable storage | Deployed in local mode on both devices with the reviewed pathway `general-adult-4`; no corpus by decision (ADR-004). |
| Privacy/recovery | Ownership isolation, expiry/deletion, cancelled late jobs, protected internal services, and network traffic checks | Tested (acceptance suites, recovery exercise 2026-10-14, boundary sampling with listeners since #151). |
| Customer rehearsal | Cold startup recorded separately; ten warm runs with stage timings and failures retained | Not run. |

Inspect the public readiness check locally (development API shown; the deployed API listens on 8100, behind the gateway on 8180):

```bash
curl --fail --show-error --silent --max-time 5 \
  http://127.0.0.1:8000/api/v1/health/ready
```

Real ZRT model-health checks use the endpoint and authentication contract verified during discovery (`GET {base}/models` on loopback, auth type none). A process existing, a listening socket, a model-cache entry, or a help example is not proof of successful inference.

The rehearsal targets are next-question rendering within five seconds and final guidance within twenty seconds in at least nine of ten warm single-user runs. These are acceptance targets, not device claims. Record queue, retrieval, inference, validation, and total time separately; retain failed and timed-out runs. Missed targets require documented tuning or an explicit target revision.

The deployment record's release gates apply to a connected local customer presentation. They do not prevent mock development or claim that a synthetic flow needs a selected model or clinically reviewed content before it can be tested.

## 7. Data, failures, and recovery

Host assets locally, disable third-party analytics, and allow only approved outbound destinations. Offline local mode uses reviewed local snapshots; mock mode uses synthetic fixtures. Installing packages or acquiring models is a separate preparation activity; it does not establish that runtime requests stay local. Verify runtime traffic before making a local-processing claim.

Use least-privilege service accounts, internal data/service bindings, and deployment-supported disk encryption. No patient-content backups are enabled for this demo. Guest health content expires after 30 minutes idle or eight hours absolute, whichever comes first. Saved synthetic cases use the selected seven- or thirty-day retention period, with thirty days the default. Temporary exports expire after fifteen minutes; cleanup runs every five minutes; content-free operational events expire after thirty days.

Deletion marks the actor/case deleting, blocks reads, revokes downloads, cancels jobs, and purges all owned stores. Late workers check tombstones before publishing. Failed purge/reset keeps access blocked and prevents fixture reuse until repaired. Browser-downloaded copies are outside server deletion and must be explained to the user.

A provider connectivity failure may use a dated usable directory snapshot and show degraded status. Safety or model failure makes routine guidance unavailable. Recovery must use pinned manifests and the immutable evidence snapshot (*Future design: not built (ADR-004); local mode needs no corpus today*). Restart the model with its user unit (§10, `systemctl --user restart aware-care-zrt-model.service`) and roll the app back with the deploy workflow (ENG-08 §6). Local processing alone is not evidence of a compliance certification, healthcare outcome, or clinical validation.

## 8. Updating ZRT (re-qualification, #75)
The maintainer updates ZRT periodically to test the latest HP releases. Local guidance was qualified on a specific
runtime, so **every ZRT, model or serving change is re-qualified against the ADR-002 gates before a release relies on
it.** The gates are never relaxed to fit a result.

1. **Before updating:** record the current state with `zrt --version`, `snap list zrt` and the serving command
   (`infra/model-manifest.json` `serving.command`).
2. **Update and restart the model** with the recorded serving command. Check that the served flags match: `ps -o args=`
   on the vLLM process should show the GPU fraction, 16,384 context, one sequence, language-only, thinking off and MTP 2.
   Also record the engine version: `/opt/hp/zrt/venv/bin/python -c "import vllm; print(vllm.__version__)"`.
3. **Re-qualify** from `apps/api`, writing to `evidence/model-qualification/<date>-zrt-<version>/`. It takes about 20
   minutes, and nobody should generate guidance on the device meanwhile:
   ```bash
   Q=../../evidence/model-qualification/$(date -u +%F)-zrt-<version>; mkdir -p $Q
   MD=/opt/hp/zrt/models/hf/Qwen/Qwen3.6-35B-A3B-FP8/95a723d08a9490559dae23d0cff1d9466213d989
   ../../scripts/egress_watch.sh 'Qwen3.6-35B-A3B-FP8/|VLLM::EngineCore' > $Q/egress.log & EW=$!  # stage 6: connections and listeners (#151)
   uv run python ../../scripts/qualify_model.py identity --model-dir $MD --out $Q/identity.json
   uv run python ../../scripts/qualify_model.py failures --model-id qwen3.6-35b-a3b-fp8 --out $Q/failures.json
   uv run python ../../scripts/qualify_model.py judge    --model-id qwen3.6-35b-a3b-fp8 --out $Q/judge.json
   uv run python ../../scripts/qualify_model.py run      --model-id qwen3.6-35b-a3b-fp8 --out $Q/run.json
   kill $EW
   /opt/hp/zrt/venv/bin/python ../../scripts/qualify_model.py context --model-dir $MD --run-file $Q/run.json \
       --no-thinking --out $Q/context.json                   # read-only use of ZRT's interpreter (tokenizer)
   uv run python ../../scripts/qualify_model.py gates --identity $Q/identity.json --failures $Q/failures.json \
       --run $Q/run.json --context $Q/context.json --judge $Q/judge.json --egress $Q/egress.log --out $Q/gates.json
   ```
4. **Read the verdict in `gates.json`.**
   - **PASSED:** record it in ADR-002 ("Runtime re-qualifications") and update `infra/model-manifest.json`
     (`zrt_version_observed`, `serving.interface`) in a PR.
   - **Anything else:** investigate and record the failure. Either fix the app (as #75 did) or return to the last
     qualified runtime with `snap revert zrt` and the recorded serving command. Never release on a runtime that failed
     a gate.
5. **The live app during an update:** while no model is served, local readiness reports `degraded` and guidance fails
   visibly with a retry. Red flags and intake keep working.

## 9. ZRT services and login sessions (lingering, #139)
The ZRT snap runs its vLLM backends and proxy under the user's systemd manager. Without lingering, systemd stops that
manager, and every ZRT service with it, when the user's last login session ends. This was seen on the ZGX Fury on
2026-10-17 (#137): the model stopped 17 s after the last SSH session closed.

- **Enabled 2026-10-17 by the maintainer's decision (#139):** `loginctl enable-linger <user>` on the Nano and
  `loginctl enable-linger <user>` on the Fury. Both now report `loginctl show-user <user>` → `Linger=yes`.
- **No other change:** ZRT, CUDA, drivers and service configuration are untouched.
- **Check** after an OS reinstall or a new service account: `loginctl show-user <user> -p Linger`.
- **Undo:** `loginctl disable-linger <user>`.


## 10. The model at boot (#170)
ZRT has no autostart: there is no snap service and no boot setting. A model started with `zrt service start` keeps
running across logouts (lingering, §9), but not across a reboot. Until 2026-10-18 the Nano's model had been started by
hand from a login shell on 2026-10-15, so a reboot would have left local mode failing visibly. The Fury has had a boot
unit since #142.

- **Nano unit (2026-10-18, #170):** `infra/nano/zrt/aware-care-zrt-model.service` runs
  `infra/nano/zrt/serve-model.sh`. The script uses exactly the manifest's `serving.command` unless the optional `~/.config/aware-care-demo/model.env` (the unit's `EnvironmentFile`) sets `AWARECARE_MODEL_REVISION`, `AWARECARE_ZRT_MODE`, `AWARECARE_ZRT_URL` or `AWARECARE_CUDA_HOME`, and puts the CUDA 13.3
  toolchain first on PATH, as the login shell that started the model did. When the model is already served it exits
  at once, so enabling the unit never restarts a running model. The command, ZRT, CUDA and drivers are unchanged.
- **Install** (as the device user; `./demo.sh model` installs and starts the same unit):
  ```bash
  install -D -m 644 infra/nano/zrt/aware-care-zrt-model.service ~/.config/systemd/user/aware-care-zrt-model.service
  install -D -m 755 infra/nano/zrt/serve-model.sh ~/.local/share/aware-care-demo/zrt/serve-model.sh
  systemctl --user daemon-reload && systemctl --user enable --now aware-care-zrt-model.service
  ```
- **Proven by restarting the unit**, which is what a boot runs:
  - the Nano's model was back in 363 s and the Fury's in 120 s;
  - the app returned to ready on its own;
  - the unit-started Nano process has the qualified arguments, CUDA 13.3 and loopback-only sockets.

  Evidence: `evidence/operations/2026-10-18-recovery-exercise/`.
- **Not yet proven by a real reboot:** that needs root (neither account has passwordless sudo). The post-boot check
  (runbook §8) records the result of the next reboot automatically.
- **Changing the served model** needs a new ADR-002 qualification. Then update the manifest, this script and the
  unit's `ExecStop` together; `tests/tooling/test_recovery.py` fails if they disagree.

## 11. vLLM usage statistics (#175)
vLLM, inside ZRT, posts a usage report to `https://stats.vllm.ai` when an engine starts, and again every 600 s. The
model processes inherit the system-wide proxy variables, so the reports left both devices through the site proxy (ask your IT for the proxy). The
Nano's local copy (`~/.config/vllm/usage_stats.json`) goes back to 2026-05-26.

- **Content:** hardware and serving configuration plus a random install UUID. No prompts, outputs or patient data.
- **How it was found:** ADR-002 stage 6 caught one report during the #154 re-qualification (2026-10-18). Earlier
  stage-6 runs sampled sockets once a second and missed these sub-second connections.
- **Fix (2026-10-18):** both serve scripts export `VLLM_NO_USAGE_STATS=1`, `VLLM_DO_NOT_TRACK=1`, `DO_NOT_TRACK=1` and
  `HF_HUB_OFFLINE=1` for the model process only; ZRT is not changed.
- **Check:** the engines' environment carries the variables (`/proc/<pid>/environ`), and `usage_stats.json` stops
  growing. An engine started any other way (for example `zrt serve` by hand for a qualification) needs the same
  variables.
