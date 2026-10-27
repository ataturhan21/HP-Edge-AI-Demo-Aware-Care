# Aware Care

A healthcare navigation demo: a patient describes one concern, answers questions from the reviewed pathway
`general-adult-4` and gets guidance from the machine's own AI model, with no data leaving the machine.

**You need** an HP ZGX Nano, a ZGX Fury or another Linux machine with an NVIDIA GPU that you reach over SSH, with
Docker usable without sudo and ZRT installed. An administrator sets these up once: [Requirements and permissions](docs/wiki/Requirements.md). `demo.sh` itself never uses sudo.

> [!IMPORTANT]
> **Demonstration only. Not a medical device and not medical advice.** Everyone and everything in it is fictional.
> Do not enter real health information.

In the commands below, replace anything in `<angle brackets>` with your own value. `demo.sh` prints each command
with your values filled in.

## Run it

On the machine, over SSH, as the user who runs the demo:

1. Clone the repository into your home directory (`cd ~` first), with the URL of this repository:
   ```bash
   git clone <your-repo-url> aware-care && cd aware-care
   ```
2. Set it up:
   ```bash
   ./demo.sh setup
   ```
   It checks the machine, picks the model the machine can hold, has ZRT serve it (a download of about 9 to
   186 GB once, size shown first), builds and deploys the app, and prints how to open it. It stops at the first
   problem and prints the fix. Rerun it at any time: it skips what is done. `--dry-run` shows every step and changes nothing;
   `./demo.sh setup --mock` runs the demo without a model or Docker.
3. Open it. On your computer, run the tunnel command it prints and keep it open:
   ```bash
   ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<device-host>
   ```
   Then open http://127.0.0.1:18180 (use `127.0.0.1`, not `localhost`) and choose **Start a new consultation** or
   **Open the presenter tools**.

Which model each machine gets: [Machines and models](docs/wiki/Local-Development.md#machines-and-models).

## Several people on one machine

Every account on a machine shares Docker's containers, the ports, the GPU and ZRT; your checkout, settings and data
stay in your own home. `demo.sh` reuses what already runs and never changes another account's demo.

| On the machine | What `demo.sh` does | What you do |
|---|---|---|
| The demo already runs (another account's `./demo.sh`, or a deployment that `demo.sh` did not build) | `setup` and `local` say so, check that it answers and print the tunnel and address. It never changes, stops or removes it | Open it. For your own copy (your own data, or code you changed): `./demo.sh setup --instance my-demo --api-port 28100 --web-port 28180` |
| ZRT already serves the model, for any account, on any port | Finds it on ZRT's port or on another listening loopback port and uses it, with a note | Nothing. Do not run `./demo.sh model` again: a second copy needs the GPU memory twice |
| ZRT in system mode or in user mode | Reads both from ZRT (`zrt config get mode`, `zrt config get proxy.port`) | Nothing, or name them: `--zrt-mode user\|system`, `--zrt-port <n>` |
| Several AI jobs at once | They share one lock on the model (`/tmp/aware-care-model.lock`); the model answers one at a time | Nothing: a waiting job says what it waits for |

Each account needs Docker without sudo (the `docker` group) and its own clone of this repository. The account that
serves the model also needs `loginctl enable-linger "$USER"`, so the model keeps running after it logs out. A second
instance keeps its data in `~/.local/share/<name>`; give `status`, `stop` and `uninstall` the same `--instance`.

## Commands

| Command | What it does |
|---|---|
| `./demo.sh setup` | Everything after the clone, in order; a rerun skips what is done |
| `./demo.sh mock` | Try it without a model or Docker (scripted synthetic results) |
| `./demo.sh local` | Build and run the app with the machine's own model |
| `./demo.sh model` | Serve this machine's model with ZRT (downloads it once if needed) |
| `./demo.sh doctor` | Check the machine (GPUs, CUDA, Docker, proxy, ZRT, disk, ports) and name its model |
| `./demo.sh check-model` | Run the advisory AI regression set against the served model and write a report |
| `./demo.sh status` | Show what runs, its version and the model |
| `./demo.sh update [<tag>]` | Switch to a release (default: the latest) and restart |
| `./demo.sh stop [mock\|local]` | Stop the app; its data is kept |
| `./demo.sh uninstall [--all]` | Remove the app; see [Remove it](#remove-it) |

Every command takes `--dry-run` (print what it would do, change nothing), `--no-color` and `--help`. The other
options:
- `setup`: `--mock` (mock mode), `--rebuild` (build and deploy again).
- `model`: `--revision <rev>`, `--timeout <time>`.
- Machine and model: `--device nano|fury|auto`, `--model <label>` (a catalogue model instead of the one chosen by GPU
  memory).
- ZRT: `--zrt-mode user|system`, `--zrt-port <n>` (its proxy port), `--zrt-url <url>` (its whole address, loopback
  only). By default `demo.sh` asks ZRT (`zrt config get mode`, `zrt config get proxy.port`).
- Ports: `--port <n>` (the browser port; in mock also the device's web port). A second local instance with its own
  containers, data and ports: `--instance <name>`, `--api-port <n>`, `--web-port <n>`.
- `uninstall`: `--all`, `--with-model`, `--yes` (answer its question).

What each command does, step by step: [Local Development](docs/wiki/Local-Development.md#what-demosh-does).

## If something goes wrong

`demo.sh` stops at the first problem and prints the fix and its log file. The usual ones:

| Symptom | Fix |
|---|---|
| `Docker is not usable without sudo` | `sudo usermod -aG docker "$USER"`, then log out and back in |
| `ghcr.io does not answer`, or downloads time out | Set the proxy for your shell and for Docker, as `demo.sh` prints |
| `ZRT does not serve <model>` | `./demo.sh setup` (or only the model: `./demo.sh model`) |
| `403`, or "Open Aware Care at the address this device is set up for" | Open exactly the `http://127.0.0.1:<n>` URL it printed, not `localhost` |
| `Port <n> is in use` | mock: `./demo.sh mock --port <n>`; local: `./demo.sh local --instance my-demo --api-port <n> --web-port <n>`, with free ports |

Anything else: [Troubleshooting](docs/wiki/Troubleshooting.md).

## Remove it

> [!WARNING]
> `uninstall` deletes the app's data in `~/.local/share/aware-care-demo`: the consultations, the presenter key and the
> whole telemetry history (AI calls, timings, energy readings), so the telemetry page starts empty afterwards. To keep
> it, back it up first:
> ```bash
> tar -czf ~/aware-care-data-$(date +%Y%m%d).tar.gz -C ~/.local/share aware-care-demo
> ```
> To bring it back, extract it to the same place (`tar -xzf <file> -C ~/.local/share`) before `./demo.sh setup`.

Look first: `--dry-run` lists what it would remove and removes nothing.

| Command | Removes | Keeps |
|---|---|---|
| `./demo.sh uninstall` | The app: its 2 containers, its `:local` images, its data in `~/.local/share/aware-care-demo`, mock mode's data, and the model unit (which stops the model) | The downloaded model, `demo.sh`'s settings and logs |
| `./demo.sh uninstall --all` | Also what every instance on this machine shares: the model's serve script, the model's settings (`~/.config/aware-care-demo`), the logs and `check-model` reports (`runtime-data/demo-logs`) and the `aware-care-api:local` and `aware-care-web:local` images | The downloaded model |
| `./demo.sh uninstall --all --with-model` | Also the downloaded model in ZRT's cache (`zrt remove`, once nothing else serves it) | |

```bash
./demo.sh uninstall --all --dry-run     # see what it would remove
./demo.sh uninstall --all               # asks first (--yes answers for you)
cd ~ && rm -rf ~/aware-care             # then the checkout itself
```

What always stays: Docker and its build cache, ZRT, uv and Node, and the checkout. `demo.sh` never removes a
deployment that is not yours. Beside one that runs, `uninstall --all` is refused and says why, and
`./demo.sh uninstall --instance <name>` removes only your own instance:
- A deployment that `demo.sh` did not build (for example a release deployed by other means as `aware-care-demo`):
  stop it first through its own process.
- Another account's instance: that account runs `./demo.sh stop`.

**Start from scratch:** back up the data if you want to keep it, run `./demo.sh uninstall --all` (add `--with-model`
to download the model again too), delete the checkout, then clone and run `./demo.sh setup` as in [Run it](#run-it).

## Development

- **Checks:** `scripts/check_all.sh` runs every local check in CI order (`--fast`, `--standard`, `--full`; `--help`).
  CI (`.github/workflows/ci.yml`) runs on GitHub-hosted runners in mock mode and needs no secrets.
- **Contributing:** [Contributing](docs/wiki/Contributing.md), [Testing](docs/wiki/Testing.md).
- **Reference:** [Product Overview](docs/wiki/Product-Overview.md), [Architecture](docs/wiki/Architecture.md),
  every API setting in [`infra/.env.example`](infra/.env.example), contracts and decisions in [`spec/`](spec).

---
*Aware Care is a synthetic demonstration for HP ZGX Nano and ZGX Fury. Fictional data only. Not for clinical use.*
