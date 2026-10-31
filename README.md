# Aware Care

A healthcare navigation demo: a patient describes one concern, answers questions from the reviewed pathway
`general-adult-4` and gets guidance from the machine's own AI model, with no data leaving the machine.

**You need** an HP ZGX Nano, a ZGX Fury or another Linux machine with an NVIDIA GPU that you reach over SSH, with
Docker usable without sudo and ZRT installed. An administrator sets these up once:
[Requirements and permissions](docs/wiki/Requirements.md). `demo.sh` itself never uses sudo.

> [!IMPORTANT]
> **Demonstration only. Not a medical device and not medical advice.** Everyone and everything in it is fictional.
> Do not enter real health information.

In the commands below, replace anything in `<angle brackets>` with your own value. `demo.sh` prints each command
with your values filled in.

## Run it

On the machine, over SSH, as the user who runs the demo. It takes a few minutes when the machine already serves the
model; a first model download adds up to an hour.

1. Get the code: clone this repository into your home directory (`cd ~` first). It is public, so no sign-in
   is needed:
   ```bash
   git clone https://github.com/ataturhan21/HP-Edge-AI-Demo-Aware-Care aware-care && cd aware-care
   ```
   Cloned it before? Bring it to the latest release instead:
   ```bash
   cd ~/aware-care && ./demo.sh update
   ```
2. Set it up:
   ```bash
   ./demo.sh setup
   ```
   - **The demo already runs on this machine** (a shared ZGX, as a rule): `setup` says **It's already running:
     open it here**, with whose it is, the tunnel and the address, and stops there. Go to step 3. To run your own
     instead, see [Several people on one machine](#several-people-on-one-machine).
   - **Something only an administrator can do** (the `docker` group, the `zrt` group, lingering): before any
     download, `setup` prints one block of commands for an administrator, with your account's name filled in. Pass it
     on, log in again over SSH, and rerun `./demo.sh setup`.
   - **Otherwise** it checks the machine, has ZRT serve the model (a download of about 9 to 37 GB once, size shown
     first), builds and deploys the app, keeps the GPU power sampler running for the telemetry page (one line in your
     crontab), and prints how to open it. Long steps say how far they are: "Download: 12.3 of 37.5 GB, about 10 min
     left", "Model start: about 2 min here" (a first start in a fresh ZRT takes up to 25 min; it is not stuck).
   - It stops at the first problem with a red `✗` and the command that fixes it (`Run:`). Rerun it at any time: it
     skips what is done. `--dry-run` shows every step and changes nothing. Without a model or Docker:
     `./demo.sh setup --mock`.
3. Open it. On your computer (not the machine), run the tunnel command `setup` printed, and keep it open:
   ```bash
   ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<device-host>
   ```
   Then open http://127.0.0.1:18180 (`localhost` works too: it redirects there) and choose **Open the presenter tools**
   (Presenter: run the demo for an audience) or **Start a new consultation** (Patient: try it yourself). Lost the
   tunnel or the address? `./demo.sh open` prints them again, for whichever demo runs here.

Which model each machine gets: [Machines and models](docs/wiki/Local-Development.md#machines-and-models).

## Present it

Showing the demo to an audience with the presenter tools, from your computer's browser once `setup` has run. Every
page shows a colored strip that says which mode you are in, **Presenter mode** or **Patient mode**, with a **Switch**
link to the other one. The same steps are in the presenter tools, under **How to present**.

1. **Open the presenter tools.** Open the tunnel and keep it open:
   ```bash
   ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<device-host>
   ```
   Open http://127.0.0.1:18180 (`localhost` works too: it redirects there). Choose **Open the presenter tools**, then
   **Start presenter session**. The Scenarios page shows three quick flows and one status line, which says
   **AI ready** when the machine's model answers.
2. **Type consultations by hand in another browser.** Use a **separate browser or a private window**, not the browser
   that runs the presenter tools. That browser's tabs share one patient session, and a quick flow or **Load scenario**
   gives it to a synthetic demo patient. When a consultation typed by hand is open there, the presenter screen asks
   first: **A consultation typed by hand is open in this browser**. **Continue anyway** ends that consultation in this
   browser (its tab then says "Your session ended"); **Cancel** keeps it. Without one, nothing is asked.
3. **Run a quick flow.** Choose **Run on HP ZGX Fury** (or Nano) on a quick flow's card. It takes about 2 s on the
   Fury (11 to 25 s on the Nano), in a dialog that shows each step. **Close** keeps it running (its card shows the
   outcome); **Open the result** shows it in this same window as the **Demo patient** (no pop-up, no second tab).
   **Back to presenter** on the strip returns to the Scenarios page, where **Show again** opens it once more. The home
   page's **Start a new consultation** never shows a demo: it always starts a fresh consultation.
4. **Clear demos between audiences.** Choose **Clear demos for the next audience**: on the Scenarios page once a demo
   ran, and on **More scenarios**. It removes only the demos this browser's presenter tools created (also under
   earlier presenter sessions). Consultations typed by hand and other browsers' demos stay. A full journey on More
   scenarios (**Load scenario**) also opens in this window as the Demo patient.
5. **Show Telemetry.** **Basic** for a short story (five headline figures and one cost sentence); **Advanced** for
   every figure, the break-even against the cloud references and the calculator, and **Download PNG** for one 16:9
   slide. The device's cost per consultation needs the GPU power sampler, which `setup` keeps running. Until a figure
   is measured, it reads "Not measured" and says when it will appear, for example "Cost appears after the first full
   hour, at 15:00, with the first consultation from then on".
6. **Use any screen.** Everything works with the keyboard only (Tab, Enter; Escape closes a dialog), on a phone (the
   navigation is behind **Menu**) and on large screens and projectors.
7. **Show the controls when asked.** The page **Evidence and controls** has no tab in the presenter navigation: it
   distracted in front of an audience. Open it directly when someone asks: http://127.0.0.1:18180/presenter/controls.
   - **What the controls are:** the 5 privacy and safety controls of this build: no cloud fallback; the evidence
     corpus (none is approved, so possible explanations are marked as the model's general medical knowledge); the
     reviewed clinical pathway `general-adult-4` and its expiry; the outbound gateway (none: the app makes no outbound
     lookups); and log redaction (events are content-free). Below them, the outbound events (none).
   - **Why they show "Unverified":** a control says Verified only when the app records executed evidence for this
     exact build. This demo records none (the lean process of ADR-019 dropped that step), so all 5 say Unverified. It
     means that no proof is recorded for this build, not that a control failed.
   - **Where the evidence lives:** [`evidence/README.md`](evidence/README.md) says what counts as evidence. This
     public copy carries only the evidence files that the code and tests read, under [`evidence/`](evidence); the
     maintainer's per-release, model-qualification and drill records are not part of it.

## Several people on one machine

Every account on a machine shares Docker's containers, the ports, the GPU and ZRT; your checkout, settings and data
stay in your own home. There is no main instance: anyone can use the demo that runs, or stop it and run their own.
Its data always stays: `demo.sh` only ever deletes your own files.

| On the machine | What `demo.sh` does | What you do |
|---|---|---|
| The demo already runs (another account's `./demo.sh`, a deployment that `demo.sh` did not build, or yours with other data) | `setup` and `local` say **It's already running: open it here**, whose it is and whether it answers ready, print the tunnel and address, and stop there (also before you can use Docker) | Open it; `./demo.sh open` prints the way in again at any time. Your own copy instead: beside it, `./demo.sh setup --instance my-demo --api-port 28100 --web-port 28180`; or in its place, `./demo.sh setup --replace` (its containers are removed, its data is kept) |
| ZRT already serves the model, for any account, on any port | Finds it on ZRT's port or on another listening loopback port and uses it, with a note | Nothing. Do not run `./demo.sh model` again: a second copy needs the GPU memory twice |
| ZRT in system mode or in user mode | Reads both from ZRT (`zrt config get mode`, `zrt config get proxy.port`) | Nothing, or name them: `--zrt-mode user\|system`, `--zrt-port <n>` |
| The system ZRT already has the model (or may: outside the `zrt` group its cache cannot be read), but your ZRT runs in user mode | Stops before downloading it again; outside the `zrt` group, the administrator block names `sudo usermod -aG zrt <user>` | Rerun with `--zrt-mode system` (after the administrator's step and a new login) |
| Another model fills the GPU | Stops before the download or the start: how much memory is free, what the model asks for, and who uses the rest | Stop your other model with the command it prints, or ask its owner |
| The model was started by hand (`zrt service start`) | `status` and `doctor` say it has no unit and no watchdog; `setup` adds them (the model keeps running) | `./demo.sh setup` |
| Several AI jobs at once | They share one lock on the model (`/tmp/aware-care-model.lock`); the model answers one at a time | Nothing: a waiting job says what it waits for |

What each account needs (`setup` checks all of it before any download and prints the administrator's part as one
block of commands with your account's name):
- Docker without sudo (the `docker` group) and its own clone of this repository.
- A login over SSH as that account (`ssh <user>@localhost` works). `sudo` then `su <user>` has no systemd session,
  so `setup` stops at once.
- Only the account that serves the model: lingering, so the model keeps running after it logs out. An administrator
  runs `sudo loginctl enable-linger <user>`; `setup` stops until it is on, and `doctor` shows it.
- A second instance keeps its data in `~/.local/share/<name>`; give `status`, `open`, `stop`, `uninstall` and `fresh`
  the same `--instance`.

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
| `./demo.sh open` | Print the tunnel command and the address of the demo that runs here (anyone's), at any time |
| `./demo.sh update [<tag>]` | Switch to a release (default: the latest) and restart |
| `./demo.sh stop [mock\|local]` | Stop the app; its data is kept |
| `./demo.sh uninstall [--all]` | Remove the app; see [Remove it](#remove-it) |
| `./demo.sh fresh` | Start again: back up the data, `uninstall --all` (never the model), then `setup`; says where the backup is |

Every command takes `--dry-run` (print what it would do, change nothing), `--no-color` and `--help`. The other
options:
- `setup`: `--mock` (mock mode), `--rebuild` (build and deploy again).
- `setup` and `local`: `--replace` (replace the demo that runs here, whoever's it is: its containers are removed, its
  data is kept).
- `model`: `--revision <rev>`, `--timeout <time>`.
- Machine and model: `--device nano|fury|auto`, `--model <label>` (a catalogue model instead of the one chosen by GPU
  memory).
- ZRT: `--zrt-mode user|system`, `--zrt-port <n>` (its proxy port), `--zrt-url <url>` (its whole address, loopback
  only). By default `demo.sh` asks ZRT (`zrt config get mode`, `zrt config get proxy.port`).
- Ports: `--port <n>` (the browser port; in mock also the device's web port). A second local instance with its own
  containers, data and ports: `--instance <name>`, `--api-port <n>`, `--web-port <n>`.
- `uninstall`: `--all`, `--with-model`, `--yes` (answer its question). `fresh`: `--yes`.

What each command does, step by step: [Local Development](docs/wiki/Local-Development.md#what-demosh-does).

## If something goes wrong

`demo.sh` stops at the first problem with a red `✗`, says why, and names the command that fixes it (`Run:`), with
its log file. The usual ones:

| Symptom | Fix |
|---|---|
| `An administrator must do … once` (Docker is not usable without sudo, the `zrt` group, lingering) | Pass the block it prints to an administrator: it names your account, for example `sudo usermod -aG docker <user>`. Then log out and back in over SSH, and rerun |
| `ghcr.io does not answer`, or downloads time out | Set the proxy for your shell and for Docker, as `demo.sh` prints |
| `ZRT does not serve <model>` | `./demo.sh setup` (or only the model: `./demo.sh model`) |
| `403`, or "Open Aware Care at the address this device is set up for" | The browser uses another port than the tunnel `demo.sh` printed: open exactly the `http://127.0.0.1:<n>` address it printed (`localhost:<n>` redirects there) |
| `Port <n> is in use` | mock: `./demo.sh mock --port <n>`; local: `./demo.sh local --instance my-demo --api-port <n> --web-port <n>`, with free ports |
| `... cannot reach your systemd session` | Log in over SSH as that user (`ssh <user>@localhost`), not with `sudo` then `su`, and rerun |

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

On a shared machine, `uninstall` (like `stop`) also removes the containers of the demo that runs, whoever's it is;
their data stays. Ran your own beside it with `--instance <name>`? Give `uninstall` the same `--instance <name>`.

| Command | Removes | Keeps |
|---|---|---|
| `./demo.sh uninstall` | The app: its 2 containers, its `:local` images, its data in `~/.local/share/aware-care-demo` (with the model's serve script), mock mode's data, the power sampler's crontab line, and the model unit and its watchdog (which stops the model) | The downloaded model, `demo.sh`'s settings and logs, your other crontab lines |
| `./demo.sh uninstall --all` | Also the model's settings (`~/.config/aware-care-demo`), the logs and `check-model` reports (`runtime-data/demo-logs`), and the older `aware-care-api:local` and `aware-care-web:local` images | The downloaded model |
| `./demo.sh uninstall --all --with-model` | Also the downloaded model in ZRT's cache (`zrt remove`, once nothing else serves it) | |

1. See what it would remove:
   ```bash
   ./demo.sh uninstall --all --dry-run
   ```
2. Remove it. It asks first (`--yes` answers for you):
   ```bash
   ./demo.sh uninstall --all
   ```
3. Delete the checkout:
   ```bash
   cd ~ && rm -rf ~/aware-care
   ```

What always stays: Docker and its build cache, ZRT, uv and Node, and another account's data (`demo.sh` only ever
deletes paths of your own data root).

**Start from scratch:** `./demo.sh fresh` backs up the data (the `tar` command above), runs `./demo.sh uninstall --all`
(never `--with-model`: the model stays downloaded) and `./demo.sh setup` again, and says where the backup is
(`--dry-run` shows each step). For a new checkout too: back up, `./demo.sh uninstall --all`, delete the checkout, then
clone and run `./demo.sh setup` as in [Run it](#run-it).

## Development

- **Checks:** `scripts/check_all.sh` runs every local check in CI order (`--fast`, `--standard`, `--full`; `--help`).
  CI (`.github/workflows/ci.yml`) runs on GitHub-hosted runners in mock mode and needs no secrets.
- **Contributing:** [Contributing](docs/wiki/Contributing.md), [Testing](docs/wiki/Testing.md).
- **Reference:** [Product Overview](docs/wiki/Product-Overview.md), [Architecture](docs/wiki/Architecture.md),
  every API setting in [`infra/.env.example`](infra/.env.example), contracts and decisions in [`spec/`](spec).

---
*Aware Care is a synthetic demonstration for HP ZGX Nano and ZGX Fury. Fictional data only. Not for clinical use.*
