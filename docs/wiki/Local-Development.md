# Local Development

How to run the demo on any ZGX Nano or Fury, or any other NVIDIA Linux machine (see "Other machines" below):
`./demo.sh setup` after the clone (or, step by step, `./demo.sh model` and `./demo.sh local`; `./demo.sh mock` for the
development servers without a model); see the [README](<your-repo-url>/blob/main/README.md#run-it).
What the machine and the user need (sudo, Docker group, credentials, ZRT mode, ports):
[Requirements and permissions](Requirements). Every API setting: [`infra/.env.example`](<your-repo-url>/blob/main/infra/.env.example).

## What demo.sh does

The same steps by hand, for when you need to change one. Logs: `runtime-data/demo-logs/`.

**`setup`** (#549) runs, in order and with the same code, `doctor`'s checks (strictly: the first ✗ stops it with its
fix; Docker and the network get `local`'s checks, whose fixes are complete), `model` (nothing when ZRT serves the model,
else a copy ZRT has, else the download with its size first; the unit; the wait until ZRT lists it), then `local`'s build
and deploy, and the Open it box. A rerun skips what is done: the model when ZRT serves it, the build and deploy when
`nano_deploy.py status` shows this checkout's commit (no local changes) in local mode with the same model and ZRT
address, both containers running and readiness `ready` (`--rebuild` builds and deploys anyway). `--mock` runs `mock`
instead (nothing when it already runs and answers ready on the same ports). `--dry-run` prints every step and changes
nothing. `./demo.sh` with no command asks once on a terminal, then runs `setup`; without a terminal it prints the help
(exit 2), and with `--dry-run`, `--mock` or `--rebuild` it runs `setup` with that option.

**`mock`**: `uv sync --python 3.12.15` in `apps/api` and, when `package-lock.json` changed, `npm ci` in
`apps/web` (never when `node_modules` is a link). It creates a throwaway presenter key `runtime-data/presenter-dev.key`
and starts, in the background, `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` (the next free port if 8000
is taken) with `AWARECARE_ALLOWED_ORIGINS=http://127.0.0.1:<browser port>`, and `npm run dev` with
`AWARECARE_WEB_PORT` (5173, or `--port`) and `AWARECARE_API_TARGET`. It waits until `/api/v1/health/ready` answers
`ready`; if it does not within 2 minutes, it stops both servers again. Tunnel: `ssh -N -p <ssh-port> -L 15173:127.0.0.1:5173 <user>@<device-host>`.

**`local`**, from the repository root:
1. Device: on a machine whose GPU is neither a GB10 nor a GB300, the generic profile (see "Other machines"). Else
   the model `/v1/models` at ZRT's address (step 2) lists (`qwen3.6-35b-a3b-fp8` or `Qwen/Qwen3.6-35B-A3B-FP8`
   Nano, `qwen3.8-flash-next-fp8` or `Qwen/Qwen3.8-Flash-Next-FP8` Fury, any revision; see "Model names"), else the GPU name from `nvidia-smi` (GB10 Nano, GB300 Fury); `--device` overrides it.
2. Checks: `docker info` as your user (and, #549, a note when the `docker` first on PATH comes from a conda or
   virtualenv environment and hides another), buildx (`infra/deploy/find_buildx.sh`, which `build_images.sh` uses
   too, in this order: `docker buildx version`, the standalone `docker-buildx version`, the plugin binary
   `docker-buildx version` run directly from `~/.docker/cli-plugins`, `/usr/local/lib/docker/cli-plugins`,
   `/usr/libexec/docker/cli-plugins` or `/usr/lib/docker/cli-plugins`, then `docker docker-buildx --version` only when
   it answers as buildx: the Docker CLI answers it with its own version), `https://ghcr.io` reachable directly or
   through `HTTPS_PROXY` (and then the Docker daemon's own proxy, shown by `docker info`), and ZRT listing the model.
   ZRT's address is `--zrt-url`, else `--zrt-port <n>`, else `AWARECARE_ZRT_URL`, else ZRT's proxy on the port
   `zrt config get proxy.port` names, else 8080 (loopback only). When it does not list the model and neither
   `--zrt-url` nor `--zrt-port` was given, a `Ready` service in `zrt services` for the model with its own loopback
   `API ENDPOINT` that lists it is used instead, with a note (#535); else another listening loopback port that lists
   the model (for example another account's ZRT on a shared device, #632). Steps 4 and 5 pass the address as `--zrt-base-url <url>`, which
   replaces the config's `zrt.base_url`; the API gets it as `AWARECARE_MODEL_BASE_URL`, and `status` shows it. Right
   after Docker, before the network and model checks, the device ports (API 8100, web 8180, or `--api-port`/`--web-port`) must be free unless this
   instance's own containers hold them (`Port <n> is in use on this device`).
3. `infra/deploy/build_images.sh --platform linux/arm64 --commit "$(git rev-parse HEAD)" --api-ref
   aware-care-demo-api:local --web-ref aware-care-demo-web:local --metadata-dir runtime-data/demo-logs/build --load`
   (it forwards the shell's proxy variables to the build).
4. `python3 infra/deploy/nano_deploy.py --config infra/deploy/demo-zgx-<device>.json presenter-key` (kept if it exists).
5. `python3 infra/deploy/nano_deploy.py --config infra/deploy/demo-zgx-<device>.json deploy --mode local --model-id
   <model> --release-tag "$(git describe --tags)" --app-commit "$(git rev-parse HEAD)" --api-image
   aware-care-demo-api:local --web-image aware-care-demo-web:local --no-pull --allow-unpinned`. It checks the model,
   starts both containers (loopback, host network, restart after a reboot), runs one synthetic consultation while it holds
   the device's model lock (it waits at most 300 s for another AI job, #578) and prints `outcome: SUCCEEDED`. With `--port <n>` the script adds `--origin http://127.0.0.1:<n>` before `deploy`.
6. Tunnel: `ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<device-host>`, then http://127.0.0.1:18180.

**`model`**: does nothing when ZRT already serves the model under any of its names. Otherwise it looks for a copy
ZRT has downloaded, under any revision (`zrt models`, and ZRT's cache `/opt/hp/zrt/models/hf/<org>/<name>/<revision>/`;
`AWARECARE_ZRT_HOME` changes the base), preferring the qualified revision, then `main`; `--revision <rev>` asks for one.
Only when there is no copy does it run `zrt pull hf:<repo>@<revision>` (the qualified revision from
`infra/<device>/zrt/serve-model.sh`). Then: `install -D` of `infra/<device>/zrt/aware-care-zrt-model.service` to
`~/.config/systemd/user/` and of `serve-model.sh` to `~/.local/share/aware-care-demo/zrt/`, the chosen revision
written to `~/.config/aware-care-demo/model.env` (`AWARECARE_MODEL_REVISION=<rev>`, read by the unit, so no script is
edited), `systemctl --user daemon-reload`, `systemctl --user enable` and `systemctl --user restart --no-block
aware-care-zrt-model.service` (the unit is a oneshot: a blocking start would wait silently for the whole load, #533).
A revision other than the qualified one is printed as a note, never a failure. A service registers with ZRT's proxy on
the port ZRT is set to; asked for another port (`--zrt-port`, `--zrt-url`), `model` stops before it changes anything
and prints `zrt -m <mode> config set proxy.port <n>` (ZRT's own setting) or the option for ZRT's port. An address
other than 8080 goes to `model.env` as `AWARECARE_ZRT_URL`; without it the serve scripts ask
`zrt config get proxy.port` themselves for their "already served" check. `--dry-run` prints all of this and
changes nothing. Starting takes about 6 minutes on a Nano, 2 on a Fury; `loginctl enable-linger "$USER"` keeps it
after logout. While it waits, `model` prints the unit's state, ZRT's service state and the last journal line every 30
seconds. It stops at once when the unit fails or stops, or when ZRT's service keeps restarting (its PID changes, or it
is younger than the unit's start while not Ready), and gives up after 15 minutes on a Nano, 8 on a Fury
(`--timeout 20m` changes it). Then it prints the last 25 journal lines, `zrt logs tail <label>` and the likely cause with
its fix: the CUDA toolchain, GPU memory held by another process, ZRT not answering, or lingering off.

**Watchdog (#640).** With the unit, `model` installs `infra/zrt/model-watchdog.sh` beside `serve-model.sh` and the
device's `aware-care-zrt-watchdog.service` and `.timer`, clears its restart count and runs `systemctl --user enable --now
aware-care-zrt-watchdog.timer` (also when ZRT already serves the model through an installed unit). Every minute it
restarts the model unit (`systemctl --user restart --no-block`) only when the unit is enabled and has been active for 5
minutes, ZRT's proxy does not list the model and no ZRT service process for it is alive; a unit stopped or disabled on
purpose is never started. After 3 restarts within an hour it gives up until ZRT lists the model again or `model` runs.
Its decisions: `journalctl --user -u aware-care-zrt-watchdog.service`; `status` and `doctor` show it on or off and its
last restart; `uninstall` removes it first.

**Model names.** ZRT lists a model by its `--label` (our serve scripts: `qwen3.6-35b-a3b-fp8`,
`qwen3.8-flash-next-fp8`) or, started without one, by its repository id (`Qwen/Qwen3.6-35B-A3B-FP8`); its own tables
write `hf:<repo>@<revision>`. `demo.sh`, the deploy preflight and the API accept the same model under any of these
names (any case, any revision, with or without `hf:`), and the API sends its requests under the name ZRT lists
(`apps/api/app/runtime/model_ids.py`). Only another model is "not served".

**Other machines (#537).** `apps/api/app/runtime/hardware.py` reads the DMI product name, the GPUs
(`nvidia-smi --query-gpu=index,name,memory.total,compute_cap,driver_version`), `MemTotal` from `/proc/meminfo`, the
CUDA toolkit with `bin/nvcc` and `uname -m`. Its class: `gb10` (unified memory: usable memory is `MemTotal`), `gb300`,
`grace` (GB200) or `discrete` (usable memory is the sum of the GPUs' memory). `./demo.sh doctor` prints all of it, the
Docker, proxy, ZRT, disk and port checks, and the model it will use.

- *How the tier is chosen:* [`infra/models/catalog.json`](<your-repo-url>/blob/main/infra/models/catalog.json)
  lists the models largest first; the first entry whose `hardware` holds the class and whose `min_memory_gb` (5 %
  tolerance: a "24 GB" card reports 23.99 GiB) and `min_gpus` the machine meets wins (#549: on several GPUs only those the model spreads over count, a
  power of two up to `max_tensor_parallel`, so four 16 GB cards get Qwen3-14B, not Qwen3.6). GB300: Qwen3.8-Flash-Next;
  64 GB and more: Qwen3.6-35B-A3B; 24 to 63 GB: Qwen3-14B-FP8; 12 to 23 GB: Qwen3-8B-FP8; below that, `mock`.
  `--model <label>` picks an entry by name; `--device nano|fury` forces a ZGX device's qualified model.
- *What runs:* a GB10 or GB300 keeps the Nano's or Fury's serve script, unit and deploy configuration unchanged.
  Any other machine gets `infra/generic/zrt/serve-model.sh` and its unit: `demo.sh model` writes
  `AWARECARE_MODEL_URI`, `AWARECARE_MODEL_LABEL`, the revision and ZRT's mode to `model.env`, and the entry's serving
  flags (`hardware.py serve-args`: memory fraction, `--max-model-len`, `--max-num-seqs`, vLLM flags and, on several
  GPUs, `--gpu-devices 0,1`, from which ZRT sets vLLM's tensor parallel size) to `~/.local/share/aware-care-demo/zrt/serve.args`. `demo.sh local` builds the images for
  the machine's architecture (`linux/amd64` or `linux/arm64`), writes a detected `device-inventory.json` and neutral
  `telemetry-pricing.json` (device price 0, the Nano's reviewed cloud prices) and, #549, the model's
  `model-manifest.json` to `<data root>/device/`: for a candidate a manifest `<label>@<revision>-candidate` with no
  qualification or runtime record, so the pages do not show the Nano's qualification date. It deploys
  with `infra/deploy/demo-generic.json`, `--device-name` from DMI, `--device-files <dir>` (mounted read-only for the
  API) and `--expected-arch`.
- *ZRT's mode:* every `zrt` call gets `-m <mode>`: `--zrt-mode user|system`, else `AWARECARE_ZRT_MODE`, else
  `zrt config get mode`, else `system`.
- *Candidate:* an entry chosen by memory that was not qualified (ADR-002) on that hardware; on the Nano and the Fury
  their models are *qualified*. `./demo.sh check-model` runs the AI regression set (`scripts/ai_regression/run.sh
  here`) against the served model through an API started in local mode, prints the table and the run time and writes
  `runtime-data/demo-logs/check-model-<host>-<time>.json` (machine, model, result) to send back. It is advisory: it
  exits 0 unless the run itself fails.
- *Add a catalogue entry:* a Hugging Face repository with a vLLM-supported architecture and a licence that allows the
  use; pin `revision` to a commit (`curl https://huggingface.co/api/models/<repo>` shows `sha`); set `label`, `repository_id`,
  `license`, `tier`, `size_gb`, `hardware`, `status_by_hardware`, `min_memory_gb`, `min_gpus`, `max_tensor_parallel` (a
  divisor of the KV heads), a `serving.default` variant (`gpu_memory_fraction`, `max_model_len`, `max_num_seqs`, `extra` vLLM flags; speculative decoding only
  where tested) and an inline `manifest` (`manifest_id`, `model` with `served_model_id` and `revision`,
  `qualification.status: candidate`). Keep the list largest first; `tests/tooling/test_hardware.py` checks it.

**`stop [mock|local]`** removes the two containers or stops the mock servers (without a target: mock when it runs, else the containers; never a workflow deployment); **`uninstall`** also deletes
`~/.local/share/aware-care-demo` and `runtime-data/api`, the `:local` images, the model unit and its watchdog. **`uninstall --all`**
removes everything `demo.sh` added, to start from scratch: also the model's serve script, `~/.config/aware-care-demo`,
the logs and `check-model` reports in `runtime-data/demo-logs` and the `aware-care-api:local` / `aware-care-web:local` images; with
`--with-model`, the downloaded model (`zrt remove <uri>`, once `zrt services` no longer shows it served after our unit
stopped). It lists everything and asks first (`--yes` skips the question), and ends with what stays: the checkout,
Docker, ZRT and, without `--with-model`, the model. **`update [<tag>]`** (default: the newest `v*` tag) refuses a
checkout with local changes, runs `git fetch --tags`, refuses a tag without `demo.sh` (older than v0.16.1-demo.1) before
the checkout, checks out the tag and verifies that `HEAD` is that tag before it restarts mock or local, whichever
`demo.sh` had running. `--dry-run` holds for every command: it prints what it would do and changes nothing.

**Device notes.** The deploy configuration (`infra/deploy/demo-zgx-nano.json`, `demo-zgx-fury.json`) sets the device
name on the pages, the ports (8100, 8180), the browser origin and, for the Fury, its records in `infra/fury/`. The
Fury's serve script puts `/usr/local/cuda/bin` first on PATH (the distribution's CUDA 12.0 cannot build GB300 kernels)
and keeps vLLM on loopback. The Nano's puts `/usr/local/cuda-13.3/bin` first. Both scripts choose CUDA in this order (#533):
`AWARECARE_CUDA_HOME` from `~/.config/aware-care-demo/model.env`, the qualified directory, the highest
`/usr/local/cuda-13.*` with `bin/nvcc`, then `/usr/local/cuda`; they log the choice and stop when none has `nvcc`.
`serve-model.sh cuda` prints the choice; `demo.sh model` checks it before it starts the unit. A second local instance on other
ports: `--instance <name> --api-port <n> --web-port <n>` (or `AWARECARE_DEMO_INSTANCE`, `AWARECARE_DEMO_API_PORT`,
`AWARECARE_DEMO_WEB_PORT`); its data goes to `~/.local/share/<name>` unless `AWARECARE_DEMO_DATA_ROOT` says otherwise.
`local` checks that the device ports are free before it builds.
`local`, `stop`, `uninstall` and `update` leave alone an instance whose images `demo.sh` did not build (a release from
the deploy workflow on the maintainer's devices), nor one whose API container keeps its data outside your data root
(another account's `./demo.sh` instance, #634). Where such a release or instance runs, `local` and `setup` say so instead of
setting up: the release, whether it answers ready, and the tunnel and address to open it; a second instance
(`--instance my-demo --api-port 28100 --web-port 28180`) is only for your own copy (#632).

**Development servers in local mode:** start the API with `AWARECARE_MODE=local AWARECARE_MODEL_ID=<model>` in front of
`uv run`; on a Fury also `AWARECARE_MODEL_MANIFEST=infra/fury/model-manifest.json
AWARECARE_DEVICE_INVENTORY=infra/fury/device-inventory.json AWARECARE_TELEMETRY_PRICING=infra/fury/telemetry-pricing.json`.

## Machines and models

`demo.sh` reads the GPUs and their memory and picks the first model of
[`infra/models/catalog.json`](<your-repo-url>/blob/main/infra/models/catalog.json)
the machine can hold (`--model <label>` overrides it; how: "Other machines" above):

| Machine (usable GPU memory) | Model | Status |
|---|---|---|
| HP ZGX Fury (GB300) | `qwen3.8-flash-next-fp8` (186 GB) | qualified on the Fury |
| 64 GB and more: HP ZGX Nano (GB10, unified), HP Z8 with 2x RTX PRO 5000 72GB, ... | `qwen3.6-35b-a3b-fp8` (37 GB; on up to 2 GPUs) | qualified on the Nano, candidate elsewhere |
| 24 to 63 GB | `qwen3-14b-fp8` (16 GB) | candidate |
| 12 to 23 GB | `qwen3-8b-fp8` (9.5 GB) | candidate |
| below 12 GB, or no NVIDIA GPU | none: `./demo.sh mock` | |

Several GPUs count only as far as the model spreads over them (ZRT is told which GPUs to use, and sets vLLM's tensor
parallel size from them). A *candidate* was chosen by memory and has not been qualified on that hardware: the app shows
its model manifest as `<model>@<revision>-candidate`, with no qualification date, and `./demo.sh check-model` runs the
advisory AI regression set against it and writes a report to send back. On other machines `demo.sh` builds the images
for the machine's own architecture (`linux/amd64` or `linux/arm64`); the release images stay `linux/arm64` for the two
ZGX devices.

## Install and run (on the device)

```bash
cd ~/aware-care/apps/api && uv sync --python 3.12.15      # isolated backend environment
cd ~/aware-care/apps/web && npm ci                          # frontend dependencies
# terminal 1: API on 127.0.0.1:8000 (mock mode by default); --reload restarts it on code changes
cd ~/aware-care/apps/api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
# terminal 2: web on 127.0.0.1:5173, /api proxied to 8000
cd ~/aware-care/apps/web && npm run dev
```

From your computer: `ssh -N -p <ssh-port> -L 15173:127.0.0.1:5173 <user>@<device-host>` (`<ssh-port>` is the device's
SSH port, usually 22), then open exactly http://127.0.0.1:15173. The API accepts only that origin by default:
`localhost` or another local port gets `403 "This request origin is not allowed"`; add other addresses to
`AWARECARE_ALLOWED_ORIGINS`. Other ports: `uvicorn --port`, and `AWARECARE_WEB_PORT` / `AWARECARE_API_TARGET` for Vite
(see above).

## Presenter screens locally

Since #487 one Vite server serves both roles, as the deployed gateway does: `/api` is the patient API and
`/presenter-api` the presenter API. Start both servers with a throwaway key, and the dev server signs `/presenter-api`:
```bash
(umask 077 && python3 -c 'import secrets; print(secrets.token_hex(32))' > /tmp/presenter-dev.key)
cd ~/aware-care/apps/api && AWARECARE_PRESENTER_KEY_FILE=/tmp/presenter-dev.key uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
cd ~/aware-care/apps/web && AWARECARE_PRESENTER_KEY_FILE=/tmp/presenter-dev.key npm run dev
```
Open http://127.0.0.1:15173 and choose **Open the presenter tools** on the home page. You can also go straight to
http://127.0.0.1:15173/presenter/scenarios. Without the key, `/presenter-api` answers `403 PRESENTER_REQUIRED`, and the
presenter tools say that presenter access is not enabled.

## Rules that matter while coding

- Read [`spec/authority.md`](<your-repo-url>/blob/main/spec/authority.md) first. Preserve every requirement, screen, module and operation ID.
- Keep clinical rules and persistence in the owning backend module, not in UI components.
- Change contracts and tests together; after `spec/api/openapi.json` run `npm run gen:api` in `apps/web`.
- Never install application packages into ZRT or system Python; never commit `.env` files, runtime data or health content.
- Don't change drivers, CUDA, ZRT, authentication/TLS or existing services without explicit authorization.

## Reset

Stop the API, delete `~/aware-care/runtime-data/api/`, start it again. Inside the app: *End session and reset* or *Delete all consultations*.
