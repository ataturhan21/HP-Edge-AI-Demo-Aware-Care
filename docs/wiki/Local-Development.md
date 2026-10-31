# Local Development

How to run the demo on any ZGX Nano or Fury, or any other NVIDIA Linux machine (see "Other machines" below):
`./demo.sh setup` after the clone (or, step by step, `./demo.sh model` and `./demo.sh local`; `./demo.sh mock` for the
development servers without a model); see the [README](https://github.com/ataturhan21/HP-Edge-AI-Demo-Aware-Care/blob/main/README.md#run-it).
What the machine and the user need (sudo, Docker group, credentials, ZRT mode, ports):
[Requirements and permissions](Requirements). Every API setting: [`infra/.env.example`](https://github.com/ataturhan21/HP-Edge-AI-Demo-Aware-Care/blob/main/infra/.env.example).

## What demo.sh does

The same steps by hand, for when you need to change one. Logs: `runtime-data/demo-logs/`.

**Reading its output (#648).** A green `✓` is done. A yellow `!` is worth a look; its `Fix:` line says in plain words
what to do, often nothing. A red `✗` stopped it: the lines under it say why, and `Run:` names the command that fixes
it. Dim lines are detail, and `$` lines are commands a dry run prints instead of running. Color shows only on a
terminal; `--no-color` or `NO_COLOR=1` turn it off and `FORCE_COLOR=1` turns it on.

**`setup`** (#549) first looks for a demo that already runs here (#696): this instance's containers, anyone's, or,
when Docker is not usable for you, whatever answers on this instance's web port. Then it says **It's already running:
open it here**, with whose it is, whether it answers ready, the tunnel and the address, and exits 0 (`--replace` and
`--instance` stay available; README "Several people on one machine"). Next, before any download (#694), the
administrator's steps: the `docker` group (`docker info` says "permission denied"), the `zrt` group (ZRT in user mode,
the model not served, and the system ZRT's cache holds it or cannot be read: `/opt/hp/zrt` is `drwxrws--- root:zrt`),
lingering (when this account serves the model) and a login session. They come in one block:
```
  ✗ An administrator must do 2 things for alice, once, before setup can go on
    Docker: alice is not in the docker group, and demo.sh never uses sudo.
    Lingering: off, so the model you serve stops when alice logs out.
    Copy this block to an administrator:
      sudo usermod -aG docker alice
      sudo loginctl enable-linger alice
    Then log out, log in again over SSH as alice (ssh alice@<this machine>; not sudo then su), and rerun:
    Run: ./demo.sh setup
```
`model` checks the same for the `zrt` group, lingering and the session; `local` for Docker and the session; `doctor`
shows the block without stopping. Then `setup` runs, in order and with the same code, `doctor`'s checks (strictly: the first ✗ stops it with its
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
   on both devices since #646, any revision; see "Model names"); the GPU name from `nvidia-smi` decides first (GB10 Nano, GB300 Fury), since both serve the same model; `--device` overrides it.
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
6. Power sampler (#678): `python3 infra/deploy/nano_deploy.py --data-root <data root> power-sampler` keeps the GPU
   power sampler running, so Telemetry measures the device's energy and its cost per consultation. It copies
   `infra/telemetry/power_sampler.py` to `<data root>/telemetry/`, adds one line to your user crontab (with a comment
   above it) and starts the sampler now; `setup` runs the same step when the app already runs. The line is the
   runbook's (section 10b): `* * * * * /usr/bin/flock -n <data root>/telemetry/sampler.lock /usr/bin/python3
   <data root>/telemetry/power_sampler.py --out <data root>/data/local/power >> <data root>/telemetry/sampler.log 2>&1`.
   Cron starts it within a minute after it exits or after a reboot, with no login session; `flock` keeps one. One per
   data root, so a second instance (`--instance`) gets its own, since each API reads its own data root. A line that
   already names this data root's script is kept, so a rerun changes nothing (the maintainer's Nano and Fury have had
   one since 2026-10-16). A local-mode deploy adds the same line itself, which is how the deploy workflows keep it on
   the maintainer's devices. `--dry-run` prints the command and the line. When the crontab cannot be written,
   `setup` and `local` say so with a yellow `!` and go on. `status` (for your own local deployment) and `doctor`
   show `Power sampler: on` with the age of its last reading, or `off`.
7. Tunnel: `ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<device-host>`, then http://127.0.0.1:18180
   (`localhost:18180` redirects there, #690). `./demo.sh open` prints both again at any time (#695).

**`open`** (#695) prints the Open it box (the tunnel command for this login and host, from `SSH_CONNECTION`, and the
address) for the demo that runs here: this checkout's mock mode, else this instance's containers, whoever's (their web
port and their own origin, from the web container), else whatever answers on this instance's web port. It says whose
it is and whether it answers ready. When nothing runs it stops with `Run: ./demo.sh setup`. It reads only.

**`fresh`** (#698): `./demo.sh fresh` starts again from scratch, after one question (`--yes` answers it): 1. `tar -czf
~/aware-care-data-<date>.tar.gz -C ~/.local/share aware-care-demo` (the README's backup; `<instance>-data-<date>` for a
second instance, a time added when the file exists), checked with `tar -tzf`; a failed backup stops it before anything
is removed. 2. `./demo.sh uninstall --all --yes` (never `--with-model`: the downloaded model stays). 3. `./demo.sh
setup`. Then it says where the backup is and how to bring it back (`./demo.sh stop`, `tar -xzf <file> -C
~/.local/share`, `./demo.sh setup`). `--dry-run` shows each step.

**Progress (#697).** Long steps say how far they are. The model download: the size of ZRT's copy as it grows
(`du -sb` of `<ZRT's cache>/hf/<repo>`) against the catalogue's size, as "Download: 12.3 of 37.5 GB, about 10 min
left". The model start: "Model start: about 2 min here" (6 on a Nano), also in a dry run, with how long it has run.
On a terminal the text follows the spinner; without one, a dim line every 30 seconds.

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
changes nothing. Starting takes about 6 minutes on a Nano, 2 on a Fury; a first start in a fresh ZRT loads the model,
then builds its GPU kernels (about 25 minutes on the Fury). Lingering (`sudo loginctl enable-linger <user>`, by an
administrator) keeps it after logout; `setup` and `doctor` warn when it is off. While it waits, `model` prints every 30
seconds why it still waits, the unit's state, ZRT's service state and the last journal line. It stops at once when the
unit fails or stops, or when ZRT's service keeps restarting (its PID changes, or it is younger than the unit's start
while not Ready). After the usual 15 minutes on a Nano, 8 on a Fury, it waits on only while ZRT's service process for
the model lives and ZRT's log for the model keeps changing (`vllm-*.log` in `~/.local/share/zrt/run` in user mode, in
`/opt/hp/zrt/run` in system mode, else `zrt logs tail <label>`): it stops as stuck when the log has not changed for
10 minutes, and after 60 minutes in all (#644). `--timeout 20m` is a hard limit instead. Then it prints the last 25
journal lines, `zrt logs tail <label>` and the likely cause with its fix: the CUDA toolchain, GPU memory held by another
process (never the model's own, such as `VLLM::EngineCore`), ZRT not answering, or lingering off.

**A model started by hand (#702).** When ZRT serves the model through a service process of your own account (vLLM
runs as the account that started it, in user and in system mode) and the model unit is not enabled, someone ran
`zrt service start` outside `demo.sh`: it has no unit and no watchdog, so it does not come back after a crash or a
reboot. `status` and `doctor` say so; `setup` and `model` install and enable the unit and its watchdog, and start the
unit only when its serve script will see the model served (then it exits at once), so no second copy starts.

**GPU memory (#702).** Before a download or a start, `model` and `setup` compare the GPU's free memory (`nvidia-smi
--query-gpu=memory.total,memory.used`) with what the serve settings ask for (`--gpu-memory-fraction`: 0.40 on a Nano,
0.20 on a Fury, the catalogue's elsewhere). Too little stops them before the download, with the processes that use the
GPU and, when your own ZRT serves another model, `zrt -m <mode> service stop <its URI>`. A GPU without memory figures (a
GB10's unified memory) is not checked.

**Before a download or a unit install (#644).** `setup`, `model` and `local` first check that `systemctl --user`
reaches your systemd session; `sudo` then `su <user>` has none ("Failed to connect to bus: Permission denied"), so they
stop at once: log in over SSH as that user (`ssh <user>@localhost` works). `doctor` shows it. In user mode, a copy of
the model in the system ZRT's cache (`$ZRT_HOME/models`, default `/opt/hp/zrt/models`; a revision folder you cannot
read still counts when its parent lists it) stops `setup`, `model` and `doctor` before the download: in the `zrt`
group, rerun with `--zrt-mode system`; outside it, an administrator runs `sudo usermod -aG zrt <user>`, then log in
again and rerun with `--zrt-mode system`. User mode looks for downloaded copies and free disk in its own cache
(`~/.local/share/zrt/models`). `doctor` and `setup` show the CUDA version the serve script will use (its
`bin/nvcc --version`) and warn below 13. When another listening port serves the model (another account's ZRT) and your own model unit is
not enabled, `doctor` and `setup` say so in the ZRT section and skip the lingering and watchdog checks: they matter to
the account that serves the model (#651).

**Watchdog (#640).** With the unit, `model` installs `infra/zrt/model-watchdog.sh` beside `serve-model.sh` and the
device's `aware-care-zrt-watchdog.service` and `.timer`, clears its restart count and runs `systemctl --user enable --now
aware-care-zrt-watchdog.timer` (also when ZRT already serves the model through an installed and enabled unit; a
leftover unit that was never enabled gets none, #666). Every minute it
restarts the model unit (`systemctl --user restart --no-block`) only when the unit is enabled and has been active for 5
minutes, ZRT's proxy does not list the model and no ZRT service process for it is alive; a unit stopped or disabled on
purpose is never started. After 3 restarts within an hour it gives up until ZRT lists the model again or `model` runs.
Its decisions: `journalctl --user -u aware-care-zrt-watchdog.service`; `status` and `doctor` show it on or off and its
last restart; `uninstall` removes it first.

**Model names.** ZRT lists a model by its `--label` (our serve scripts: `qwen3.6-35b-a3b-fp8` on
both devices) or, started without one, by its repository id (`Qwen/Qwen3.6-35B-A3B-FP8`); its own tables
write `hf:<repo>@<revision>`. `demo.sh`, the deploy preflight and the API accept the same model under any of these
names (any case, any revision, with or without `hf:`), and the API sends its requests under the name ZRT lists
(`apps/api/app/runtime/model_ids.py`). Only another model is "not served".

**Other machines (#537).** `apps/api/app/runtime/hardware.py` reads the DMI product name, the GPUs
(`nvidia-smi --query-gpu=index,name,memory.total,compute_cap,driver_version`), `MemTotal` from `/proc/meminfo`, the
CUDA toolkit with `bin/nvcc` and `uname -m`. Its class: `gb10` (unified memory: usable memory is `MemTotal`), `gb300`,
`grace` (GB200) or `discrete` (usable memory is the sum of the GPUs' memory). `./demo.sh doctor` prints all of it, the
Docker, proxy, ZRT, disk and port checks, and the model it will use.

- *How the tier is chosen:* [`infra/models/catalog.json`](https://github.com/ataturhan21/HP-Edge-AI-Demo-Aware-Care/blob/main/infra/models/catalog.json)
  lists the models largest first; the first entry whose `hardware` holds the class and whose `min_memory_gb` (5 %
  tolerance: a "24 GB" card reports 23.99 GiB) and `min_gpus` the machine meets wins (#549: on several GPUs only those the model spreads over count, a
  power of two up to `max_tensor_parallel`, so four 16 GB cards get Qwen3-14B, not Qwen3.6). 64 GB and more (the GB300 too, #646):
  Qwen3.6-35B-A3B; 24 to 63 GB: Qwen3-14B-FP8; 12 to 23 GB: Qwen3-8B-FP8; below that, `mock`.
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
`~/.local/share/aware-care-demo` and `runtime-data/api`, the `:local` images, the model unit and its watchdog, and,
first, the power sampler's crontab line (`nano_deploy.py power-sampler --remove`, which also stops the sampler; every
other crontab line stays). **`uninstall --all`**
removes everything `demo.sh` added, to start from scratch: also the model's serve script, `~/.config/aware-care-demo`,
the logs and `check-model` reports in `runtime-data/demo-logs` and the `aware-care-api:local` / `aware-care-web:local` images; with
`--with-model`, the downloaded model (`zrt remove <uri>`, once `zrt services` no longer shows it served after our unit
stopped). It lists everything and asks first (`--yes` skips the question), and ends with what stays: the checkout,
Docker, ZRT and, without `--with-model`, the model. Beside someone else's demo that answers ready, the list says that
removing it takes it away from everyone who uses it, and names `./demo.sh open` instead (#702). **`update [<tag>]`**
(default: the newest `v*` tag) refuses a checkout with local changes (with one command that keeps them on a branch:
`git switch -c my-changes && git commit -qam 'My changes'`), runs `git fetch --tags`, refuses a tag without `demo.sh`
(older than v0.16.1-demo.1) before the checkout, checks out the tag and verifies that `HEAD` is that tag before it
restarts mock or local, whichever `demo.sh` had running. Without a tag named it never moves to an older release than
the checkout's own, and when origin has nothing newer it says so (#702). Any origin is accepted: a fork or a copy of
this repository updates to the `v*` release tags it publishes. `--dry-run` holds for every command: it prints what it would do and changes nothing.

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
**Shared machines: no main instance (#644).** Container names are the same for every account, so this instance's
containers may run the maintainer's workflow release, another account's `./demo.sh` instance (its data outside your
data root, #634) or your own with other data. Anyone may use it, or stop it and run their own. `local` and `setup` say
whose it is, whether it answers ready and the tunnel and address to open it, and exit 0 (#632). `--replace` says what
happens first (its containers are removed, its data is kept), builds, then runs `docker rm -f` on the two containers
just before the deploy, so a failed build leaves the running demo alone; with nothing running it just deploys.
`stop`, `uninstall` and `uninstall --all` never refuse because of whose demo runs; they remove its containers and
delete only paths of your own data root (a path another account owns is kept, with a note). `update` restarts `local`
only when the running instance is your own. A second instance (`--instance my-demo --api-port 28100 --web-port 28180`)
runs your own copy beside it.

**Development servers in local mode:** start the API with `AWARECARE_MODE=local AWARECARE_MODEL_ID=<model>` in front of
`uv run`; on a Fury also `AWARECARE_MODEL_MANIFEST=infra/fury/model-manifest.json
AWARECARE_DEVICE_INVENTORY=infra/fury/device-inventory.json AWARECARE_TELEMETRY_PRICING=infra/fury/telemetry-pricing.json`.

## Machines and models

`demo.sh` reads the GPUs and their memory and picks the first model of
[`infra/models/catalog.json`](https://github.com/ataturhan21/HP-Edge-AI-Demo-Aware-Care/blob/main/infra/models/catalog.json)
the machine can hold (`--model <label>` overrides it; how: "Other machines" above):

| Machine (usable GPU memory) | Model | Status |
|---|---|---|
| 64 GB and more: HP ZGX Nano (GB10, unified), HP ZGX Fury (GB300), HP Z8 with 2x RTX PRO 5000 72GB, ... | `qwen3.6-35b-a3b-fp8` (37 GB; on up to 2 GPUs) | qualified on the Nano; on the Fury by the owner's decision (ADR-018 amendment 1), with its own memory fraction 0.20; candidate elsewhere |
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
SSH port, usually 22), then open http://127.0.0.1:15173 (Vite redirects `localhost:15173` there, #690). The API accepts
only that origin by default: another local port gets `403 "This request origin is not allowed"`; add other addresses to
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

- Read [`spec/authority.md`](https://github.com/ataturhan21/HP-Edge-AI-Demo-Aware-Care/blob/main/spec/authority.md) first. Preserve every requirement, screen, module and operation ID.
- Keep clinical rules and persistence in the owning backend module, not in UI components.
- Change contracts and tests together; after `spec/api/openapi.json` run `npm run gen:api` in `apps/web`.
- Never install application packages into ZRT or system Python; never commit `.env` files, runtime data or health content.
- Don't change drivers, CUDA, ZRT, authentication/TLS or existing services without explicit authorization.

## Reset

Stop the API, delete `~/aware-care/runtime-data/api/`, start it again. Inside the app: *End session and reset* or *Delete all consultations*.
