"""#525: ./demo.sh replaces the README's manual Path A and Path B.

The commands it relies on (docker, curl, nvidia-smi, zrt) are stand-ins on PATH, driven by environment variables, so
nothing touches Docker, the network, the GPU or ZRT. `local --dry-run` runs every check and prints the commands that
`local` would run instead of running them. The tests run without a terminal, so the output is plain (#533) unless a
test sets FORCE_COLOR.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "demo.sh"
NANO_MODEL = "qwen3.6-35b-a3b-fp8"
FURY_MODEL = NANO_MODEL  # #646: the Fury serves the Nano's model

DOCKER = """\
#!/bin/sh
case "$1" in
  info)
    if [ "${FAKE_DOCKER:-ok}" = denied ]; then
      echo "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock" >&2; exit 1
    fi
    echo "Server:"
    [ -n "${FAKE_DAEMON_PROXY:-}" ] && echo " HTTPS Proxy: $FAKE_DAEMON_PROXY"
    exit 0 ;;
  buildx)
    # #535, #549: FAKE_BUILDX=plugin (default), standalone (only the docker-buildx program), dir (only the plugin binary
    # in a cli-plugins directory), docker-cmd (only `docker docker-buildx`) or none
    [ "${FAKE_BUILDX:-plugin}" = plugin ] || { echo "docker: unknown command: docker buildx" >&2; exit 1; }
    echo "docker $*" >> "${FAKE_BUILDX_LOG:-/dev/null}"
    echo "github.com/docker/buildx v0.20.0" ;;
  docker-buildx)
    # the real Docker CLI answers `docker docker-buildx --version` with its own version (seen on the Nano, #549)
    if [ "${FAKE_BUILDX:-plugin}" = docker-cmd ]; then
      echo "docker $*" >> "${FAKE_BUILDX_LOG:-/dev/null}"; echo "github.com/docker/buildx v0.29.1"
    else echo "Docker version 29.2.1, build a5c7197"; fi ;;
  container)
    # FAKE_CONTAINERS="<name>=<image> ...", else FAKE_RUNNING_IMAGE for any name
    if [ -n "${FAKE_CONTAINERS:-}" ]; then
      img=""
      for c in $FAKE_CONTAINERS; do for a in "$@"; do [ "$a" = "${c%%=*}" ] && img=${c#*=}; done; done
      [ -n "$img" ] || exit 1
    else
      [ -n "${FAKE_RUNNING_IMAGE:-}" ] || exit 1
      img=$FAKE_RUNNING_IMAGE
    fi
    case "$*" in
      *State.Running*) echo true ;;
      *Config.Image*) echo "$img" ;;
      *Config.Env*) printf '["AWARECARE_MODEL_BASE_URL=%s"%s]\n' "${FAKE_APP_ZRT_URL:-http://127.0.0.1:8080/v1}" \
        "${FAKE_WEB_ENV:-}" ;;
      *Config.Labels*) echo "${FAKE_RELEASE:-}" ;;
      *Mounts*) echo "${FAKE_DATA_MOUNT:-}" ;;  # #634: the host directory the API's data comes from
      *-f*) ;;
      *) echo '[{"State": {"Status": "running", "Running": true, "ExitCode": 0}, "Image": "sha256:1", "Config": {}}]' ;;
    esac ;;
  images)  # #668: `docker images -q <release pattern>`: FAKE_RELEASE_IMAGES, one ID per line
    for i in ${FAKE_RELEASE_IMAGES:-}; do echo "$i"; done ;;
  image)  # FAKE_IMAGES: the images that exist
    if [ "$2" = inspect ]; then
      for i in ${FAKE_IMAGES:-}; do [ "$i" = "$3" ] && exit 0; done; exit 1
    fi
    echo "docker $*" >> "${FAKE_DOCKER_LOG:-/dev/null}" ;;
  rm)  # #590: FAKE_RM_FAIL="<name> ...": removing these containers fails, and they keep running
    echo "docker $*" >> "${FAKE_DOCKER_LOG:-/dev/null}"
    for a in "$@"; do for f in ${FAKE_RM_FAIL:-}; do
      [ "$a" = "$f" ] && { echo "Error response from daemon: cannot remove container \"$f\": could not kill" >&2; exit 1; }
    done; done
    exit 0 ;;
  # every call that changes something is logged
  run|create|start|stop|kill|build|compose|pull|volume|network|system|builder)
    echo "docker $*" >> "${FAKE_DOCKER_LOG:-/dev/null}" ;;
  *) exit 0 ;;
esac
"""

# The standalone buildx program (#535): answers only with FAKE_BUILDX=standalone.
DOCKER_BUILDX = """\
#!/bin/sh
[ "${FAKE_BUILDX:-plugin}" = standalone ] || exit 127
echo "docker-buildx $*" >> "${FAKE_BUILDX_LOG:-/dev/null}"
echo "github.com/docker/buildx v0.29.1"
"""

# curl: ZRT's proxy (127.0.0.1:8080, or FAKE_PROXY_PORT) answers FAKE_MODELS; with FAKE_REAL_CURL, any other
# /v1/models goes to a real server the test runs (#535: a ZRT service's own endpoint); with FAKE_PROXY_PORT and no
# FAKE_REAL_CURL, nothing else answers (#549).
CURL = """\
#!/bin/sh
for a in "$@"; do
  case "$a" in
    http://127.0.0.1:${FAKE_PROXY_PORT:-8080}/v1/models) ;;
    */v1/models) [ -n "${FAKE_REAL_CURL:-}" ] && exec "$FAKE_REAL_CURL" "$@"
      [ -n "${FAKE_PROXY_PORT:-}" ] && exit 7 ;;
    */api/v1/health/ready) [ -n "${FAKE_REAL_CURL:-}" ] && exec "$FAKE_REAL_CURL" "$@" ;;
  esac
done
for a in "$@"; do
  case "$a" in
    */v1/models)
      if [ -n "${FAKE_STARTED:-}" ] && [ -f "$FAKE_STARTED" ]; then printf '%s' "${FAKE_MODELS_AFTER:-}"; exit 0; fi
      printf '%s' "${FAKE_MODELS:-}"; exit 0 ;;
  esac
done
for a in "$@"; do
  case "$a" in
    */api/v1/health/ready) [ -n "${FAKE_READY:-}" ] && printf '{"readiness":"%s"}' "${FAKE_READINESS:-ready}"; exit 0 ;;
  esac
done
for a in "$@"; do
  case "$a" in
    --noproxy) [ "${FAKE_DIRECT:-ok}" = ok ] && exit 0; exit 28 ;;
  esac
done
[ "${FAKE_VIA_PROXY:-ok}" = ok ] && exit 0
exit 28
"""

# nvidia-smi: FAKE_SMI_CSV answers the hardware query (#537: index, name, memory, compute capability, driver), else
# FAKE_GPU (a bare name) answers any query; the banner names CUDA 13.0.
NVIDIA_SMI = """\
#!/bin/sh
case "$*" in *query-compute-apps*) printf '%s' "${FAKE_GPU_APPS:-}"; exit 0 ;; esac
# #702: "<total MiB>, <used MiB>" for the free-memory check (empty: no figures, as on a GB10)
case "$*" in *memory.total,memory.used*) [ -n "${FAKE_GPU_MEM:-}" ] && printf '%s\\n' "$FAKE_GPU_MEM"; exit 0 ;; esac
if [ -n "${FAKE_SMI_CSV:-}" ]; then
  case "$*" in *--query-gpu=*) printf '%s\\n' "$FAKE_SMI_CSV" ;; *) echo "| Driver Version: 580.95.05  CUDA Version: 13.0 |" ;; esac
  exit 0
fi
[ -n "${FAKE_GPU:-}" ] || exit 9
echo "$FAKE_GPU"
"""

# zrt: `models` and `services` print ZRT's tables (FAKE_ZRT_MODELS, FAKE_ZRT_SERVICES); every call is logged.
ZRT = """\
#!/bin/sh
echo "zrt $*" >> "${FAKE_ZRT_LOG:-/dev/null}"
if [ "$1" = -m ]; then shift 2; fi  # #537: the mode (user or system)
case "$1" in
  config) case "$*" in *proxy.port*) echo "${FAKE_ZRT_PORT:-8080}" ;; *) echo "${FAKE_ZRT_MODE:-system}" ;; esac ;;
  version) echo "zrt version 0.43.0" ;;
  models) printf '%s\\n' "${FAKE_ZRT_MODELS:-}" ;;
  services) [ -n "${FAKE_ZRT_DOWN:-}" ] && exit 1; printf '%s\\n' "${FAKE_ZRT_SERVICES:-}" ;;
  logs) echo "vllm: engine core died (zrt logs stand-in)" ;;
  pull) if [ -n "${FAKE_PULL_FAIL:-}" ]; then echo "fetching shards"; echo "error: 403 Forbidden from huggingface.co"; exit 1; fi
        # #697: a download that grows (sparse files: nothing is written to disk)
        if [ -n "${FAKE_PULL_DIR:-}" ]; then mkdir -p "$FAKE_PULL_DIR"
          for n in 1 2 3 4; do truncate -s "${n}0G" "$FAKE_PULL_DIR/model.safetensors"; sleep 1; done; fi
        echo zrt-stand-in "$@" ;;
  *) echo zrt-stand-in "$@" ;;
esac
"""

# systemctl: `show -p <property> --value` answers from FAKE_ACTIVE, FAKE_SUB, FAKE_RESTARTS, FAKE_SINCE (the unit's
# InactiveExitTimestamp) and FAKE_ENTERED (its ActiveEnterTimestamp); a start or restart of the model unit creates
# FAKE_STARTED. #640: `is-enabled` and `is-active` answer FAKE_ENABLED and FAKE_ACTIVE for the model unit, and for the
# watchdog's timer "enabled" and "active" when FAKE_WD_TIMER=on (else "disabled", "inactive"). #644: with FAKE_NO_BUS
# set, every call fails as it does without a systemd user session (`sudo` then `su <user>`).
SYSTEMCTL = """\
#!/bin/sh
if [ -n "${FAKE_NO_BUS:-}" ]; then
  echo "systemctl $*" >> "${FAKE_SYSTEMCTL_LOG:-/dev/null}"
  echo "Failed to connect to bus: Permission denied" >&2; exit 1
fi
case "$1 $2" in
  "--user show-environment") echo "HOME=/home/alice"; exit 0 ;;
  "--user show")
    case "$*" in
      *ActiveState*) echo "${FAKE_ACTIVE:-}" ;;
      *SubState*) echo "${FAKE_SUB:-}" ;;
      *NRestarts*) echo "${FAKE_RESTARTS:-0}" ;;
      *InactiveExitTimestamp*) echo "${FAKE_SINCE:-}" ;;
      *ActiveEnterTimestamp*) echo "${FAKE_ENTERED:-}" ;;
    esac
    exit 0 ;;
  "--user is-enabled"|"--user is-active")
    case "$2 $3" in
      "is-enabled "*watchdog*) [ "${FAKE_WD_TIMER:-}" = on ] && v=enabled || v=disabled ;;
      "is-active "*watchdog*) [ "${FAKE_WD_TIMER:-}" = on ] && v=active || v=inactive ;;
      "is-enabled "*) v=${FAKE_ENABLED:-disabled} ;;
      *) v=${FAKE_ACTIVE:-inactive} ;;
    esac
    echo "$v"; case "$v" in enabled|active) exit 0 ;; esac; exit 1 ;;
esac
echo "systemctl $*" >> "${FAKE_SYSTEMCTL_LOG:-/dev/null}"
case "$*" in *watchdog*) ;; *enable*--now*|*restart*) [ -n "${FAKE_STARTED:-}" ] && touch "$FAKE_STARTED" ;; esac
exit 0
"""

JOURNALCTL = """\
#!/bin/sh
echo "journalctl $*" >> "${FAKE_JOURNAL_LOG:-/dev/null}"
printf '%s\\n' "${FAKE_JOURNAL:-}"
"""

LOGINCTL = "#!/bin/sh\necho \"${FAKE_LINGER:-yes}\"\n"  # #644: FAKE_LINGER=no: lingering off
# df: free space (doctor's and setup's disk checks) is FAKE_FREE_GB, never the runner's own disk (#549: a CI runner
# had 13 GB free, so setup stopped at the model's disk check)
DF = "#!/bin/sh\necho Avail\necho \"${FAKE_FREE_GB:-2000}G\"\n"
# #678: `crontab -l` prints the file FAKE_CRONTAB_FILE when it exists, else $FAKE_CRONTAB; without either, "no crontab"
# and exit 1, as the real one. `crontab -` writes the new crontab to FAKE_CRONTAB_FILE (exit 3 without one).
CRONTAB = """#!/bin/sh
case "$1" in
  -l) if [ -n "${FAKE_CRONTAB_FILE:-}" ] && [ -f "$FAKE_CRONTAB_FILE" ]; then cat "$FAKE_CRONTAB_FILE"; exit 0; fi
      [ -n "${FAKE_CRONTAB:-}" ] || { echo "no crontab for $USER" >&2; exit 1; }
      printf '%s\\n' "$FAKE_CRONTAB" ;;
  -) [ -n "${FAKE_CRONTAB_FILE:-}" ] || { echo "crontab stand-in: no FAKE_CRONTAB_FILE" >&2; exit 3; }
     cat > "$FAKE_CRONTAB_FILE" ;;
  *) exit 2 ;;
esac
"""
# ss: a port in FAKE_BUSY_PORTS is in use; #632: `ss -Hltn` lists FAKE_LISTEN_PORTS as listening on loopback
SS = """\
#!/bin/sh
if [ "$*" = -Hltn ]; then
  for p in ${FAKE_LISTEN_PORTS:-}; do echo "LISTEN 0 4096 127.0.0.1:$p 0.0.0.0:*"; done
  exit 0
fi
for p in ${FAKE_BUSY_PORTS:-}; do
  case "$*" in *"sport = :$p") echo "LISTEN 0 4096 127.0.0.1:$p 0.0.0.0:*"; exit 0 ;; esac
done
exit 0
"""
# mock's tools: CI runners may have neither uv nor Node (a dry run only asks for their versions)
# uv: `sync` and `run` log what they would install or start (FAKE_TOOL_LOG); `run` records its PID (FAKE_PIDS) and
# stays up. #537 check-model's `uv run ... run_cases.py <cases> <out>` writes FAKE_REPORT (or a passing report) to <out>.
UV = """\
#!/bin/sh
case "$*" in
  *run_cases.py*)
    prev=""; out=""
    for a in "$@"; do case "$prev" in *cases.json) out=$a ;; esac; prev=$a; done
    echo "PASS RF01 red_flag_screen urgent"
    echo "env AWARECARE_MODEL_ID=$AWARECARE_MODEL_ID AWARECARE_MODEL_BASE_URL=$AWARECARE_MODEL_BASE_URL" >> "${FAKE_UV_LOG:-/dev/null}"
    [ -n "${FAKE_NO_REPORT:-}" ] && exit 1
    printf '%s' "${FAKE_REPORT:-$PASSING}" > "$out" ;;
  sync*) echo "uv $*" >> "${FAKE_TOOL_LOG:-/dev/null}" ;;
  run*) echo "uv $*" >> "${FAKE_TOOL_LOG:-/dev/null}"; echo $$ >> "${FAKE_PIDS:-/dev/null}"; exec sleep 60 ;;
  *) echo uv 0.0.0-stand-in ;;
esac
"""
PASSING_REPORT = ('{"summary": {"cases": 63, "urgent_recall": "20/20", "medicine_instructions_published": 0, '
                  '"expected_publishes": "25/25", "health_concerns_accepted": "10/10", "false_alarms_advisory": [], '
                  '"non_health_not_refused_advisory": [], "gate": "PASS", "gate_failures": []}, "cases": []}')
NODE = "#!/bin/sh\necho v24.0.0-stand-in\n"
NPM = """\
#!/bin/sh
echo "npm $*" >> "${FAKE_TOOL_LOG:-/dev/null}"
case "$1" in run) echo $$ >> "${FAKE_PIDS:-/dev/null}"; exec sleep 60 ;; esac
exit 0
"""

NANO_REPO = "Qwen/Qwen3.6-35B-A3B-FP8"
NANO_PINNED = "95a723d08a9490559dae23d0cff1d9466213d989"
FURY_REPO = NANO_REPO


def zrt_models(*uris: str) -> str:
    """`zrt models` as ZRT prints it (URI | NAME | REVISION | ...)."""
    rows = [f"│ {u} │ {u[3:].split('@')[0]} │ {u.split('@')[1]} │ 37.49 GB │ 2026-10-14 │ ✓ │" for u in uris]
    return "\n".join(["┌───┐", "│ URI │ NAME │ REVISION │ SIZE │ MODIFIED │ INTEGRITY │", *rows, "└───┘"])


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\(B")


def normalised(out: str, tmp: Path, root: Path) -> str:
    """Dry-run output without what differs between checkouts and runs: paths, commits, tags, the local-changes note."""
    out = out.replace(str(tmp), "<TMP>").replace(str(root), "<ROOT>")
    out = re.sub(r"(--commit|--app-commit) [0-9a-f]{40}", r"\1 <HEAD>", out)
    out = re.sub(r"--release-tag \S+", "--release-tag <TAG>", out)
    lines = out.split("\n")
    if len(lines) > 1:
        lines[1] = "<VERSION>"  # the header's tag or commit
    # #648: the local-changes note and its fix line
    return "\n".join(line for line in lines if "checkout has local changes" not in line
                     and "nothing, if you meant it" not in line)


def served(*models: str) -> str:
    return '{"object":"list","data":[%s]}' % ",".join('{"id":"%s","object":"model"}' % m for m in models)


def alive(pid: int) -> bool:
    """Whether the process runs (a zombie, exited but not yet reaped, does not)."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, IndexError):
        return False


class DemoScript(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="demo-sh-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, text in (("docker", DOCKER), ("docker-buildx", DOCKER_BUILDX), ("curl", CURL), ("nvidia-smi", NVIDIA_SMI), ("zrt", ZRT),
                           ("systemctl", SYSTEMCTL), ("loginctl", LOGINCTL), ("journalctl", JOURNALCTL),
                           ("uv", UV), ("node", NODE), ("npm", NPM), ("ss", SS), ("df", DF), ("crontab", CRONTAB)):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        clean = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()
                 and not k.startswith(("FAKE_", "SSH_", "AWARECARE_", "AWARE_CARE_", "CONDA_", "VIRTUAL_ENV"))
                 and k not in ("NO_COLOR", "FORCE_COLOR")}
        self.env = {**clean, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(self.tmp / "home"),
                    "USER": "alice", "SSH_CONNECTION": "10.1.1.5 50000 192.0.2.3 2222",
                    "AWARECARE_DEMO_LOG_DIR": str(self.tmp / "logs"),
                    # ZRT's home (proxy.json, the model cache): empty unless a test fills it
                    "AWARECARE_ZRT_HOME": str(self.tmp / "zrt-home"), "FAKE_ZRT_LOG": str(self.tmp / "zrt.log"),
                    # #533: the CUDA toolchains the serve script may choose (the qualified ones unless a test says)
                    "AWARECARE_CUDA_ROOT": str(self.cuda_root("cuda-13.3", "cuda")), "AWARECARE_DEMO_POLL_SECONDS": "1",
                    # #537: no machine unless a test names one (an empty stand-in for /: no DMI, no meminfo)
                    "AWARECARE_HW_ROOT": str(self.tmp / "no-machine"), "PASSING": PASSING_REPORT,
                    "AWARECARE_DEMO_REMOTE_TIMEOUT": "2",
                    # #549: never the machine's own buildx plugin (/usr/libexec/docker/cli-plugins on the Nano)
                    "AWARECARE_DOCKER_PLUGIN_DIRS": str(self.tmp / "no-plugins"),
                    # check-model takes the model lock: its own file, never the device's (another AI run may hold that)
                    "AWARE_CARE_MODEL_LOCK": str(self.tmp / "model.lock")}

    def cuda_root(self, *dirs: str, name: str = "cuda-root", release: str = "") -> Path:
        """Toolchains with a bin/nvcc; with a release, `nvcc --version` names it (#644)."""
        root = self.tmp / name
        root.mkdir(exist_ok=True)
        for d in dirs:
            nvcc = root / d / "bin/nvcc"
            nvcc.parent.mkdir(parents=True)
            nvcc.write_text("#!/bin/sh\n" + (f"echo 'Cuda compilation tools, release {release}, V{release}.48'\n"
                                               if release else ""))
            nvcc.chmod(0o755)
        return root

    def demo(self, *args: str, script: Path = SCRIPT, **env: str) -> subprocess.CompletedProcess:
        self.assertTrue(script.exists(), f"{script} is missing")
        return subprocess.run(["bash", str(script), *args], env={**self.env, **env}, capture_output=True, text=True,
                              timeout=60, stdin=subprocess.DEVNULL)

    # ------------------------------------------------------------------ device detection

    def test_detects_the_device_from_the_served_model(self):
        for gpu, device in (("NVIDIA GB10", "Nano"), ("NVIDIA GB300", "Fury"), ("", "Nano")):
            with self.subTest(device=device, gpu=gpu):
                run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FAKE_GPU=gpu)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn(f"Device: ZGX {device} (ZRT serves {NANO_MODEL})", run.stdout)
                self.assertIn(f"demo-zgx-{device.lower()}.json", run.stdout)

    def test_646_a_gb300_serving_the_nanos_model_is_a_fury(self):
        """#646: both devices serve qwen3.6-35b-a3b-fp8, so the served model alone made a GB300 a "Nano" (the Nano's
        deploy configuration, inventory and prices). The GPU decides, also for status and on a service endpoint."""
        for names in ((NANO_MODEL,), (NANO_REPO,), (f"hf:{NANO_REPO}@main",)):
            with self.subTest(served=names):
                run = self.demo("local", "--dry-run", FAKE_MODELS=served(*names), FAKE_GPU="NVIDIA GB300")
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn(f"Device: ZGX Fury (ZRT serves {names[0]})", run.stdout)
                self.assertIn("demo-zgx-fury.json", run.stdout)
                self.assertNotIn("demo-zgx-nano.json", run.stdout)
        run = self.demo("status", FAKE_MODELS=served(NANO_MODEL), **self.machine("gb300"))
        self.assertIn("(demo-zgx-fury.json)", run.stdout)

    def test_falls_back_to_the_gpu_name_then_asks_for_the_model(self):
        run = self.demo("local", "--dry-run", FAKE_GPU="NVIDIA GB300")
        self.assertIn("Device: ZGX Fury (GPU NVIDIA GB300)", run.stdout)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(f"ZRT does not serve {FURY_MODEL}", run.stderr)
        self.assertIn(f"zrt pull hf:{NANO_REPO}@{NANO_PINNED}", run.stderr)
        self.assertIn("./demo.sh model --device fury", run.stderr)

        run = self.demo("local", "--dry-run", FAKE_GPU="NVIDIA GB10")
        self.assertIn("Device: ZGX Nano (GPU NVIDIA GB10)", run.stdout)

    def test_device_option_overrides_and_unknown_hardware_asks_for_it(self):
        run = self.demo("local", "--dry-run", "--device", "fury", FAKE_MODELS=served(FURY_MODEL), FAKE_GPU="NVIDIA GB10")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Device: ZGX Fury (--device)", run.stdout)
        run = self.demo("local", "--dry-run")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("--device nano", run.stderr)
        # #537: no GPU at all: no local model, and mock is offered
        self.assertIn("No local model for this machine: no NVIDIA GPU found", run.stderr)
        self.assertIn("./demo.sh mock", run.stderr)

    # ------------------------------------------------------------------ #528: the served model under ZRT's names

    def test_the_same_model_under_zrts_own_names_is_detected_and_served(self):
        # #646: the same model on both devices: the GPU tells them apart
        forms = {"nano": [f"{NANO_REPO}@main", NANO_REPO, NANO_REPO.lower(), f"hf:{NANO_REPO}@main",
                          f"hf:{NANO_REPO}@{NANO_PINNED}", f"/opt/hp/zrt/models/hf/{NANO_REPO}/main"],
                 "fury": [f"{FURY_REPO}@main", FURY_REPO.upper(), f"hf:{FURY_REPO}@v2"]}
        for device, ids in forms.items():
            for served_id in ids:
                with self.subTest(served=served_id):
                    run = self.demo("local", "--dry-run", FAKE_MODELS=served("Qwen/Qwen2.5-0.5B-Instruct", served_id),
                                    FAKE_GPU="NVIDIA GB300" if device == "fury" else "NVIDIA GB10")
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn(f"Device: ZGX {device.capitalize()} (ZRT serves {served_id})", run.stdout)
                    model = NANO_MODEL if device == "nano" else FURY_MODEL
                    self.assertIn(f"ZRT serves {model} as {served_id}", run.stdout)
                    self.assertNotIn("zrt pull", run.stdout + run.stderr)

    def test_another_revision_is_a_note_never_a_failure(self):
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(f"{NANO_REPO}@main"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("! Serving revision main; this app was qualified on 95a723d…", run.stdout)
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL))  # our label, ZRT says nothing more
        self.assertIn("ZRT does not say which revision it serves", run.stdout)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_the_revision_behind_a_name_comes_from_zrt(self):
        services = f"│ 1 │ hf:{NANO_REPO}@main │ {NANO_REPO} │ - │ Ready │"
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_REPO), FAKE_ZRT_SERVICES=services)
        self.assertIn("! Serving revision main;", run.stdout)
        home = self.tmp / "zrt-home"
        home.mkdir()
        (home / "proxy.json").write_text('{"services":[{"model_uri":"hf:%s@%s","label":"%s"}]}'
                                         % (NANO_REPO, NANO_PINNED, NANO_MODEL))
        run = self.demo("status", FAKE_MODELS=served(NANO_MODEL))
        self.assertIn(f"ZRT serves {NANO_MODEL}", run.stdout)
        self.assertNotIn("Note: serving", run.stdout)  # the qualified revision
        self.assertNotIn("does not say", run.stdout)

    def test_status_names_the_served_id_and_revision(self):
        run = self.demo("status", FAKE_MODELS=served(f"{NANO_REPO}@main"))
        self.assertIn(f"ZRT serves {NANO_MODEL} as {NANO_REPO}@main", run.stdout)
        self.assertIn("! Serving revision main; this app was qualified on 95a723d…", run.stdout)

    def test_a_different_model_names_what_zrt_serves_and_how_to_serve_the_right_one(self):
        run = self.demo("local", "--dry-run", "--device", "nano", FAKE_MODELS=served("Qwen/Qwen3.8-27B-FP8@main"))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(f"ZRT does not serve {NANO_MODEL} ({NANO_REPO}, any revision)", run.stderr)
        self.assertIn("ZRT serves: Qwen/Qwen3.8-27B-FP8@main", run.stderr)
        self.assertIn(f"zrt pull hf:{NANO_REPO}@{NANO_PINNED}", run.stderr)  # nothing downloaded yet
        # Downloaded under another revision: serve that copy, never download it again.
        run = self.demo("local", "--dry-run", "--device", "nano", FAKE_MODELS=served("Qwen/Qwen3.8-27B-FP8@main"),
                        FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(f"ZRT already has {NANO_REPO} downloaded (revision main)", run.stderr)
        self.assertNotIn("zrt pull", run.stderr)
        self.assertIn("./demo.sh model --device nano", run.stderr)

    # ------------------------------------------------------------------ #528: ./demo.sh model

    def model_run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return self.demo("model", "--device", "nano", *args, FAKE_STARTED=str(self.tmp / "started"),
                         FAKE_SYSTEMCTL_LOG=str(self.tmp / "systemctl.log"), **env)

    def zrt_calls(self) -> str:
        log = self.tmp / "zrt.log"
        return log.read_text() if log.exists() else ""

    def test_model_serves_the_downloaded_main_copy_without_a_download(self):
        listing = zrt_models(f"hf:{NANO_REPO}@main", "hf:Qwen/Qwen3-32B@main")
        dry = self.model_run("--dry-run", FAKE_ZRT_MODELS=listing)
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn(f"ZRT already has {NANO_REPO}@main downloaded; serving that copy (no download)", dry.stdout)
        self.assertIn("! Serving revision main; this app was qualified on 95a723d…", dry.stdout)
        self.assertIn("AWARECARE_MODEL_REVISION=main", dry.stdout)
        self.assertIn("Dry run: nothing was downloaded, installed or started.", dry.stdout)
        self.assertFalse((self.tmp / "home").exists(), "a dry run installs nothing")
        self.assertFalse((self.tmp / "systemctl.log").exists())

        run = self.model_run(FAKE_ZRT_MODELS=listing, FAKE_MODELS_AFTER=served(f"{NANO_REPO}@main"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("pull", self.zrt_calls())
        self.assertIn(f"ZRT serves {NANO_MODEL} as {NANO_REPO}@main", run.stdout)
        env_file = self.tmp / "home/.config/aware-care-demo/model.env"
        self.assertEqual(env_file.read_text(), "AWARECARE_MODEL_REVISION=main\n")
        unit = (self.tmp / "home/.config/systemd/user/aware-care-zrt-model.service").read_text()
        self.assertIn("EnvironmentFile=-%h/.config/aware-care-demo/model.env", unit)
        calls = (self.tmp / "systemctl.log").read_text()
        self.assertIn("systemctl --user enable aware-care-zrt-model.service", calls)
        # #533: never a blocking start of the oneshot unit (it hung for the whole model load on a test machine)
        self.assertIn("systemctl --user restart --no-block aware-care-zrt-model.service", calls)
        self.assertNotIn("--now aware-care-zrt-model", calls)
        # The installed serve script, with the unit's environment, serves the @main copy under our label.
        script = self.tmp / "home/.local/share/aware-care-demo/zrt/serve-model.sh"
        out = subprocess.run(["bash", str(script)], env={**self.env, "AWARECARE_MODEL_REVISION": "main"},
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"zrt-stand-in service start hf:{NANO_REPO}@main --label {NANO_MODEL}", out.stdout)
        stop = subprocess.run(["bash", str(script), "stop"], env={**self.env, "AWARECARE_MODEL_REVISION": "main"},
                              capture_output=True, text=True, timeout=30)
        self.assertIn(f"zrt-stand-in service stop hf:{NANO_REPO}@main", stop.stdout)

    def test_model_finds_a_copy_in_zrts_cache_directory_too(self):
        copy = self.tmp / "zrt-home/models/hf" / NANO_REPO / "main"
        copy.mkdir(parents=True)
        (copy / "config.json").write_text("{}")
        run = self.model_run("--dry-run")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"ZRT already has {NANO_REPO}@main downloaded", run.stdout)
        self.assertNotIn("pull", run.stdout)

    def test_model_downloads_the_qualified_revision_only_when_no_copy_exists(self):
        run = self.model_run("--dry-run", FAKE_ZRT_MODELS=zrt_models("hf:Qwen/Qwen3-32B@main"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"pull hf:{NANO_REPO}@{NANO_PINNED}", run.stdout)
        self.assertIn(f"AWARECARE_MODEL_REVISION={NANO_PINNED}", run.stdout)
        self.assertNotIn("Note:", run.stdout)

    def test_model_prefers_the_qualified_copy_and_honours_revision(self):
        listing = zrt_models(f"hf:{NANO_REPO}@main", f"hf:{NANO_REPO}@{NANO_PINNED}")
        run = self.model_run("--dry-run", FAKE_ZRT_MODELS=listing)
        self.assertIn(f"ZRT already has {NANO_REPO}@{NANO_PINNED} downloaded", run.stdout)
        run = self.model_run("--dry-run", "--revision", "main", FAKE_ZRT_MODELS=listing)
        self.assertIn(f"ZRT already has {NANO_REPO}@main downloaded", run.stdout)
        run = self.model_run("--dry-run", "--revision", "v2", FAKE_ZRT_MODELS=listing)
        self.assertIn(f"pull hf:{NANO_REPO}@v2", run.stdout)
        self.assertIn("AWARECARE_MODEL_REVISION=v2", run.stdout)
        bad = self.model_run("--dry-run", "--revision", "main;rm")
        self.assertEqual(bad.returncode, 2)

    def test_model_does_nothing_when_the_model_is_served_under_another_name(self):
        for args in (("--dry-run",), ()):
            run = self.model_run(*args, FAKE_MODELS=served(f"{NANO_REPO}@main"))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn(f"ZRT already serves {NANO_MODEL} as {NANO_REPO}@main on http://127.0.0.1:8080/v1; nothing to do",
                          run.stdout)
        self.assertNotIn("pull", self.zrt_calls())
        self.assertFalse((self.tmp / "systemctl.log").exists())

    # ------------------------------------------------------------------ #533: the model wait and the CUDA toolchain

    def test_serve_script_chooses_the_cuda_toolchain(self):
        cases = {"nano": [(("cuda-13.3", "cuda-13.0", "cuda"), "cuda-13.3"), (("cuda-13.0",), "cuda-13.0"),
                          (("cuda-13.0", "cuda-13.10"), "cuda-13.10"), (("cuda",), "cuda")],
                 "fury": [(("cuda", "cuda-13.2"), "cuda"), (("cuda-13.2",), "cuda-13.2")]}
        for device, rows in cases.items():
            script = ROOT / f"infra/{device}/zrt/serve-model.sh"
            for i, (dirs, chosen) in enumerate(rows):
                with self.subTest(device=device, dirs=dirs):
                    root = self.cuda_root(*dirs, name=f"c-{device}-{i}")
                    out = subprocess.run(["bash", str(script), "cuda"], env={**self.env, "AWARECARE_CUDA_ROOT": str(root)},
                                         capture_output=True, text=True, timeout=30)
                    self.assertEqual((out.returncode, out.stdout.strip()), (0, str(root / chosen)), out.stderr)
        # none with nvcc: a clear failure, and the model is never started
        empty = self.cuda_root(name="c-none")
        (empty / "cuda-12.4").mkdir()
        script = ROOT / "infra/nano/zrt/serve-model.sh"
        out = subprocess.run(["bash", str(script)], env={**self.env, "AWARECARE_CUDA_ROOT": str(empty)},
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 1)
        self.assertIn("no CUDA toolchain with bin/nvcc", out.stderr)
        self.assertIn("AWARECARE_CUDA_HOME", out.stderr)
        self.assertNotIn("service start", self.zrt_calls())
        # AWARECARE_CUDA_HOME wins; starting logs the choice
        only = self.cuda_root("cuda-13.0", name="c-only")
        out = subprocess.run(["bash", str(script)], env={**self.env, "AWARECARE_CUDA_ROOT": str(only)},
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"serve-model: CUDA {only}/cuda-13.0 (qualified: /usr/local/cuda-13.3)", out.stderr)
        out = subprocess.run(["bash", str(script), "cuda"], env={**self.env, "AWARECARE_CUDA_HOME": str(only / "cuda-13.0")},
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), str(only / "cuda-13.0"))

    def test_609_model_stops_before_the_unit_when_model_env_cannot_be_written(self):
        """#609: a model.env that cannot be written (read-only folder, unreadable old file, a folder in its place)
        stops `model` with exit 1 before the unit is touched, and the old file stays as it was."""
        config = self.tmp / "home/.config/aware-care-demo"
        env = config / "model.env"
        for fault in ("read-only folder", "unreadable file", "folder in its place"):
            with self.subTest(fault=fault):
                config.mkdir(parents=True, exist_ok=True)
                (self.tmp / "systemctl.log").unlink(missing_ok=True)
                if env.is_dir():
                    shutil.rmtree(env)
                else:
                    env.unlink(missing_ok=True)
                if fault == "folder in its place":
                    env.mkdir()
                else:
                    env.write_text("AWARECARE_MODEL_REVISION=old\nAWARECARE_KEEP=this-line\n")
                try:
                    if fault == "read-only folder":
                        config.chmod(0o500)
                    elif fault == "unreadable file":
                        env.chmod(0o000)
                    run = self.model_run("--revision", "main", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"),
                                         FAKE_MODELS_AFTER=served(f"{NANO_REPO}@main"))
                finally:
                    config.chmod(0o700)
                    if env.is_file():
                        env.chmod(0o600)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn(f"Could not write {env}", run.stderr)
                self.assertNotIn("Installed aware-care-zrt-model.service (revision", run.stdout)
                calls = self.tmp / "systemctl.log"
                self.assertNotIn("restart", calls.read_text() if calls.exists() else "")
                self.assertNotIn("enable", calls.read_text() if calls.exists() else "")
                if fault == "folder in its place":
                    self.assertTrue(env.is_dir())
                else:
                    self.assertEqual(env.read_text(), "AWARECARE_MODEL_REVISION=old\nAWARECARE_KEEP=this-line\n")
                self.assertEqual(sorted(p.name for p in config.iterdir()), ["model.env"], "no temporary file is left")

    def test_609_model_env_is_replaced_whole_and_a_stray_temporary_name_does_not_matter(self):
        """#609: the writable control persists the requested revision and keeps the other lines; a leftover
        model.env.new (a folder, as in the report) no longer gets in the way."""
        config = self.tmp / "home/.config/aware-care-demo"
        config.mkdir(parents=True)
        env = config / "model.env"
        env.write_text("AWARECARE_MODEL_REVISION=old\nAWARECARE_KEEP=this-line\nAWARECARE_ZRT_MODE=user\n")
        (config / "model.env.new").mkdir()
        run = self.model_run("--revision", "main", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"),
                             FAKE_MODELS_AFTER=served(f"{NANO_REPO}@main"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(env.read_text(), "AWARECARE_KEEP=this-line\nAWARECARE_MODEL_REVISION=main\n")
        self.assertIn(f"Installed aware-care-zrt-model.service (revision main in {env})", run.stdout)
        self.assertIn("systemctl --user restart --no-block aware-care-zrt-model.service",
                      (self.tmp / "systemctl.log").read_text())
        self.assertEqual(sorted(p.name for p in config.iterdir()), ["model.env", "model.env.new"])

    def test_model_stops_before_starting_when_no_cuda_toolchain_exists(self):
        root = self.cuda_root(name="c-old")
        (root / "cuda-12.4").mkdir()
        run = self.model_run(FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"), AWARECARE_CUDA_ROOT=str(root))
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("No CUDA toolchain with bin/nvcc for the serve script", run.stderr)
        self.assertIn(f"{root}/cuda-12.4 (no nvcc)", run.stderr)
        self.assertIn("echo AWARECARE_CUDA_HOME=", run.stderr)
        self.assertFalse((self.tmp / "systemctl.log").exists(), "nothing is installed or started")
        # Only cuda-13.0: the serve script uses it, and demo.sh says so.
        root = self.cuda_root("cuda-13.0", name="c-130")
        run = self.model_run("--dry-run", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"), AWARECARE_CUDA_ROOT=str(root))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"the serve script uses {root}/cuda-13.0", run.stdout)

    def journal(self, n: int = 30) -> str:
        return "\n".join(f"journal line {i}" for i in range(1, n + 1))

    def test_model_wait_stops_at_once_when_the_unit_failed(self):
        run = self.model_run(FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"), FAKE_ACTIVE="failed", FAKE_SUB="failed",
                             FAKE_JOURNAL=self.journal(), FAKE_JOURNAL_LOG=str(self.tmp / "journal.log"),
                             FAKE_GPU_APPS="4242, python3, 30000 MiB")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("✗ The unit aware-care-zrt-model.service failed (failed)", run.stderr)
        self.assertIn("journalctl --user -u aware-care-zrt-model.service -n 25", (self.tmp / "journal.log").read_text())
        self.assertIn("Journal (journalctl --user -u aware-care-zrt-model.service -n 25)", run.stderr)
        self.assertIn("│ journal line 30", run.stderr)
        self.assertIn("│ journal line 6", run.stderr)
        self.assertNotIn("│ journal line 5\n", run.stderr)
        self.assertIn("GPU memory: other processes use the GPU now: 4242, python3, 30000 MiB", run.stderr)
        self.assertIn(f"zrt logs tail {NANO_MODEL} --lines 50", run.stderr)
        self.assertIn("vllm: engine core died", run.stderr)

    def test_model_wait_gives_up_at_the_timeout_with_status_lines(self):
        run = self.model_run("--timeout", "2", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"),
                             FAKE_ACTIVE="activating", FAKE_SUB="start", FAKE_JOURNAL="Loading safetensors shards")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("Model start: 0s so far (usually about 6 min here); unit activating (start); Loading safetensors shards",
                      run.stdout)
        self.assertIn(f"✗ ZRT did not serve {NANO_MODEL} within 2s (--timeout)", run.stderr)
        self.assertIn("systemctl --user status aware-care-zrt-model.service", run.stderr)
        self.assertEqual(self.demo("model", "--timeout", "soon").returncode, 2)

    def test_636_the_model_wait_keeps_waiting_while_zrts_service_process_lives(self):
        """#636: on the Fury (ZRT 0.43) the oneshot unit finished while vLLM still loaded, and ZRT listed the service
        as Dead; setup gave up after a minute and blamed GPU memory. It served the model a minute later."""
        def row(pid: int) -> str:
            return (f"│ {pid} │ hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d… │ qwen3.6-35b-a3b-fp8 │ - │ Dead │ 225.2 GB (VRAM) │ "
                    "1m ago │")
        finished = {"FAKE_ZRT_MODELS": zrt_models(f"hf:{NANO_REPO}@main"), "FAKE_ACTIVE": "active",
                    "FAKE_SUB": "exited", "AWARECARE_DEMO_FINISHED_GRACE": "0"}
        run = self.model_run("--timeout", "3", FAKE_ZRT_SERVICES=row(os.getpid()), **finished)  # alive: keep waiting
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"✗ ZRT did not serve {NANO_MODEL} within 3s (--timeout)", run.stderr)
        self.assertNotIn("finished, but ZRT does not list", run.stderr)
        dead = subprocess.Popen(["true"])
        dead.wait()
        began = time.monotonic()
        run = self.model_run("--timeout", "60", FAKE_ZRT_SERVICES=row(dead.pid), **finished)  # gone: stop at once
        self.assertLess(time.monotonic() - began, 30, "the grace (here 0 s) applies, not the timeout")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"✗ The unit aware-care-zrt-model.service finished, but ZRT does not list {NANO_MODEL}",
                      run.stderr)

    def test_model_wait_detects_a_restart_loop_from_zrt_services(self):
        # a test machine: the unit "activating" for 19 minutes while ZRT's service, restarted by vLLM crashes, is 3m old.
        since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 19 * 60))
        table = ("│ 0   │ 1666900 │ hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d… │ -  │ Pending │ 33.9 GB (VRAM) │ 3m ago │")
        root = self.cuda_root("cuda-13.0", name="c-qa")
        run = self.model_run(FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"), FAKE_ZRT_SERVICES=table,
                             FAKE_ACTIVE="activating", FAKE_SUB="start", FAKE_SINCE=since, AWARECARE_CUDA_ROOT=str(root))
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("ZRT's service for the model keeps restarting: the unit has been starting for 19m", run.stderr)
        self.assertIn("(PID 1666900, Pending) is only 3m00s old", run.stderr)
        self.assertIn(f"CUDA: the serve script uses {root}/cuda-13.0", run.stderr)
        self.assertIn(f"echo AWARECARE_CUDA_HOME={root}/cuda-13.0 >> ", run.stderr)
        self.assertIn("systemctl --user restart aware-care-zrt-model.service", run.stderr)
        # The same with the other table layout of `zrt services` (no index column), and a PID that changes.
        other = ("│ 1666900 │ hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d… │ qwen3.6-35b-a3b-fp8 │ - │ Pending │ 33.9 GB (VRAM) │ "
                 "3m ago │")
        run = self.model_run(FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"), FAKE_ZRT_SERVICES=other,
                             FAKE_ACTIVE="activating", FAKE_SUB="start", FAKE_SINCE=since)
        self.assertIn("(PID 1666900, Pending) is only 3m00s old", run.stderr)

    def service_row(self, pid: int, status: str = "Pending") -> str:
        return (f"│ {pid} │ hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d… │ qwen3.6-35b-a3b-fp8 │ - │ {status} │ 33.9 GB (VRAM) │ "
                "1m ago │")

    def zrt_log(self) -> Path:
        """ZRT's own log for the Nano's model, as ZRT names it in its run directory (system mode)."""
        log = self.tmp / f"zrt-home/run/vllm-hf-qwen-qwen3-6-35b-a3b-fp8-{NANO_PINNED}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("Loading safetensors checkpoint shards\n")
        return log

    def test_644_past_the_usual_wait_it_waits_while_the_model_loads_then_stops_as_stuck_or_at_the_cap(self):
        """#644: a first start in a fresh ZRT on the Fury took about 25 min (loading, then kernel builds) and setup gave
        up at 8 min. Past the usual wait it now waits while ZRT's service process lives and its log changes."""
        loading = {"FAKE_ZRT_MODELS": zrt_models(f"hf:{NANO_REPO}@main"), "FAKE_ACTIVE": "activating",
                   "FAKE_SUB": "start", "FAKE_ZRT_SERVICES": self.service_row(os.getpid()),
                   "AWARECARE_DEMO_MODEL_WAIT": "2", "AWARECARE_DEMO_STATUS_SECONDS": "1"}
        log = self.zrt_log()
        # its log keeps changing: it waits past the usual 2 s, saying why, up to the cap (here 6 s)
        stop = False

        def grow():
            while not stop:
                with log.open("a") as f:
                    f.write("compiling kernels\n")
                time.sleep(0.3)
        import threading
        writer = threading.Thread(target=grow, daemon=True)
        writer.start()
        try:
            run = self.model_run(AWARECARE_DEMO_STUCK_SECONDS="4", AWARECARE_DEMO_MAX_WAIT_SECONDS="6", **loading)
        finally:
            stop = True
            writer.join()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        # #697 (T4): each status line says how long the start has run and how long it usually takes
        self.assertRegex(run.stdout, r"Model start: 0s so far \(usually about 6 min here\); unit activating \(start\)")
        self.assertRegex(run.stdout, rf"Model start: [3-5]s so far, past 2s, still loading: its process \(PID {os.getpid()}\) "
                                     r"runs and its log changed [01]s ago \(a first start takes up to 25 min\)")
        self.assertIn(f"✗ ZRT did not serve {NANO_MODEL} within 6s, the longest demo.sh waits", run.stderr)
        # its log stands still: stuck after the stuck time (here 3 s), well before the cap
        began = time.monotonic()
        run = self.model_run(AWARECARE_DEMO_STUCK_SECONDS="3", AWARECARE_DEMO_MAX_WAIT_SECONDS="60", **loading)
        self.assertLess(time.monotonic() - began, 30)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertRegex(run.stderr, rf"✗ ZRT's service for {re.escape(NANO_MODEL)} looks stuck: its log "
                                     rf"\({re.escape(str(log))}\) has not changed for [3-5]s")
        # no log readable: `zrt logs tail` stands in for it (the stand-in prints the same line every time)
        log.unlink()
        run = self.model_run(AWARECARE_DEMO_STUCK_SECONDS="3", AWARECARE_DEMO_MAX_WAIT_SECONDS="60", **loading)
        self.assertRegex(run.stderr, rf"looks stuck: its log \(zrt logs tail {re.escape(NANO_MODEL)}\) has not changed for [3-5]s")
        # no ZRT service process left: it stops at the usual wait
        dead = subprocess.Popen(["true"])
        dead.wait()
        run = self.model_run(AWARECARE_DEMO_STUCK_SECONDS="60", **{**loading, "FAKE_ZRT_SERVICES": self.service_row(dead.pid)})
        self.assertIn(f"✗ ZRT did not serve {NANO_MODEL} within 2s, and no ZRT service process for it runs", run.stderr)

    def test_644_the_fix_never_calls_the_models_own_process_another_one(self):
        """#644: the fix text listed the model's own VLLM::EngineCore (a child of ZRT's service) as a process to stop,
        and in user mode said ZRT runs as a system service."""
        engine = subprocess.Popen(["sleep", "60"])  # a child of this process, which stands in for ZRT's service
        self.addCleanup(engine.wait)
        self.addCleanup(engine.kill)
        failed = {"FAKE_ZRT_MODELS": zrt_models(f"hf:{NANO_REPO}@main"), "FAKE_ACTIVE": "failed", "FAKE_SUB": "failed",
                  "FAKE_ZRT_SERVICES": self.service_row(os.getpid()), "FAKE_JOURNAL": "torch.OutOfMemoryError: CUDA out of memory"}
        run = self.model_run(FAKE_GPU_APPS=f"{engine.pid}, VLLM::EngineCore, 200000 MiB", **failed)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertNotIn("other processes use the GPU", run.stderr)
        self.assertIn(f"no other process uses the GPU now (only the processes of this model: {engine.pid}, "
                      "VLLM::EngineCore, 200000 MiB)", run.stderr)
        run = self.model_run(FAKE_GPU_APPS=f"{engine.pid}, VLLM::EngineCore, 200000 MiB\n1, Xorg, 120 MiB", **failed)
        self.assertIn("GPU memory: other processes use the GPU now: 1, Xorg, 120 MiB.", run.stderr)
        self.assertNotIn("VLLM::EngineCore, 200000 MiB.", run.stderr)
        # ZRT does not answer: in user mode it is the user's own, never "a system service"
        for mode, says, never in (("user", "ZRT in user mode runs as you: check zrt -m user services",
                                   "ZRT runs as a system service"),
                                  ("system", "ZRT runs as a system service: ask an administrator", "ZRT in user mode")):
            run = self.model_run("--zrt-mode", mode, FAKE_PROXY_PORT="9", **failed)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertIn(says, run.stderr)
            self.assertNotIn(never, run.stderr)

    def test_644_setup_model_and_local_need_a_login_session_before_any_download_or_install(self):
        """#644: `sudo` then `su <user>` has no systemd user session; systemctl --user failed only after a 65-minute
        download. Now setup, model and local stop at once, with the SSH login fix; doctor shows it."""
        repo = self.setup_clone()
        fix = "Log in over SSH as alice, not with sudo then su:\n    Run: ssh alice@localhost"
        for args in (("setup",), ("model", "--device", "nano"), ("local",)):
            with self.subTest(args=args):
                run = self.demo(*args, script=repo / "demo.sh", FAKE_NO_BUS="1", FAKE_MODELS=served("other"),
                                **self.machine("z8"), **self.recording())
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn("✗ systemctl --user cannot reach your systemd session (Failed to connect to bus: "
                              "Permission denied)", run.stderr)
                self.assertIn(fix, run.stderr)
                self.assertNotIn("pull", self.zrt_calls())
                self.assertEqual(self.log("build.log") + self.log("deploy.log"), "")
                self.assertFalse((self.tmp / "home/.config/systemd").exists(), "nothing is installed")
        run = self.demo("doctor", FAKE_NO_BUS="1", **self.machine("z8"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("✗ systemctl --user cannot reach your systemd session", run.stdout)
        self.assertIn(fix, run.stdout)
        self.assertIn("✓ Login session: systemctl --user reaches your systemd session",
                      self.demo("doctor", **self.machine("z8")).stdout)

    def test_644_lingering_off_is_a_clear_warning_in_doctor_and_setup(self):
        repo = self.setup_clone()
        run = self.demo("doctor", script=repo / "demo.sh", FAKE_LINGER="no", **self.machine("z8"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("! Lingering is off: the model stops when you log out", run.stdout)
        self.assertIn("    Fix: an administrator runs, once: sudo loginctl enable-linger alice", run.stdout)
        # #694 (T1): setup stops before any download with the administrator block (the model would stop at logout)
        run = self.demo("setup", "--dry-run", script=repo / "demo.sh", FAKE_LINGER="no", **self.machine("z8"))
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("Lingering: off, so the model you serve stops when alice logs out.", run.stderr)
        self.assertIn("Copy this block to an administrator:\n      sudo loginctl enable-linger alice\n", run.stderr)
        self.assertNotIn("\nModel\n", run.stdout)
        self.assertIn("✓ Lingering on: the model keeps running after you log out", self.demo("doctor").stdout)

    def test_644_doctor_and_setup_show_the_serve_scripts_cuda_version_and_warn_below_13(self):
        repo = self.setup_clone()
        for release, line in (("13.0", "✓ CUDA for the serve script: {d} (CUDA 13.0, from bin/nvcc --version)"),
                              ("12.0", "! CUDA for the serve script: {d} is CUDA 12.0, older than 13")):
            root = self.cuda_root("cuda", name=f"c-{release}", release=release)
            for args in (("doctor",), ("setup", "--dry-run")):
                with self.subTest(release=release, args=args):
                    run = self.demo(*args, script=repo / "demo.sh", AWARECARE_CUDA_ROOT=str(root), **self.machine("gb10"))
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn(line.format(d=root / "cuda"), run.stdout)

    def test_644_user_mode_never_downloads_a_model_the_system_zrt_has(self):
        """#644: in user mode setup downloaded 186 GB again (65 min) although the system ZRT's cache held the model."""
        store = self.tmp / "zrt-home/models/hf/Qwen/Qwen3.6-35B-A3B-FP8"
        rev = store / NANO_PINNED
        rev.mkdir(parents=True)
        (rev / "config.json").write_text("{}")
        groups = self.tmp / "bin/id"
        groups.write_text(f'#!/bin/sh\n[ "$1" = -nG ] && {{ echo "${{FAKE_GROUPS:-alice docker}}"; exit 0; }}\n'
                          f'exec {shutil.which("id")} "$@"\n')
        groups.chmod(0o755)
        admin = "Ask an administrator: sudo usermod -aG zrt alice, log in again, then rerun with --zrt-mode system"

        def check(args, *expect, groups_env="alice docker"):
            run = self.demo(*args, "--zrt-mode", "user", FAKE_GROUPS=groups_env, **self.machine("gb10"),
                            **self.recording())
            out = run.stdout + run.stderr
            for e in expect:
                self.assertIn(e, out)
            self.assertNotIn("pull", self.zrt_calls())
            self.assertEqual(self.changes(), "")
            return run

        # #694: outside the zrt group it is a step for an administrator, in the one block, before any download
        block = "Copy this block to an administrator:\n      sudo usermod -aG zrt alice\n"
        run = check(("model", "--device", "nano"), f"ZRT: the system ZRT already has {NANO_REPO} in {self.tmp}/zrt-home/models, "
                    "readable only for the zrt group;", block, "Run: ./demo.sh model --zrt-mode system")
        self.assertEqual(run.returncode, 1)
        check(("model", "--device", "nano"), "Serve the system ZRT's copy instead:\n    Run: ./demo.sh model --zrt-mode system", groups_env="alice zrt")
        run = check(("doctor",), "✗ The system ZRT already has this model", admin)
        self.assertEqual(run.returncode, 0)
        self.assertNotIn("Not downloaded yet", run.stdout)
        if os.geteuid() != 0:  # root reads everything
            rev.chmod(0)  # a revision folder you cannot read, seen by name through its parent
            self.addCleanup(rev.chmod, 0o755)
            check(("model", "--device", "nano"), f"{NANO_REPO} in {self.tmp}/zrt-home/models", block)
            store.chmod(0o311)  # the model's folder: searchable, not listable
            self.addCleanup(store.chmod, 0o755)
            check(("model", "--device", "nano"), f"{NANO_REPO} (its revisions are not readable for you)", block)
        # system mode serves the system ZRT's copy as before, without the stop
        run = self.demo("model", "--device", "nano", "--dry-run", "--zrt-mode", "system", **self.machine("gb10"))
        self.assertNotIn("The system ZRT already has this model", run.stdout + run.stderr)

    # ------------------------------------------------------------------ prerequisites

    def test_docker_without_permission_names_the_group_fix(self):
        run = self.demo("local", "--dry-run", FAKE_DOCKER="denied", FAKE_MODELS=served(NANO_MODEL))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("Docker: alice is not in the docker group, and demo.sh never uses sudo.", run.stderr)
        self.assertIn("      sudo usermod -aG docker alice\n", run.stderr)
        self.assertIn("Then log out, log in again over SSH as alice", run.stderr)
        self.assertNotIn("build_images.sh", run.stdout)

    def test_missing_proxy_stops_with_the_shell_and_daemon_fix(self):
        run = self.demo("local", "--dry-run", FAKE_DIRECT="timeout", FAKE_MODELS=served(NANO_MODEL))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("no proxy is set", run.stderr)
        self.assertIn("Ask your IT for the proxy address.", run.stderr)
        self.assertIn("export HTTP_PROXY=<proxy> HTTPS_PROXY=<proxy>", run.stderr)
        self.assertIn("/etc/systemd/system/docker.service.d/http-proxy.conf", run.stderr)
        self.assertIn('Environment="HTTP_PROXY=<proxy>" "HTTPS_PROXY=<proxy>"', run.stderr)
        self.assertNotIn("build_images.sh", run.stdout)

    def test_shell_proxy_without_daemon_proxy_names_the_daemon_fix(self):
        proxy = "http://proxy.example:3128/"
        run = self.demo("local", "--dry-run", FAKE_DIRECT="timeout", HTTPS_PROXY=proxy, FAKE_MODELS=served(NANO_MODEL))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("the Docker daemon has none", run.stderr)
        self.assertIn(f'Environment="HTTP_PROXY={proxy}"', run.stderr)
        run = self.demo("local", "--dry-run", FAKE_DIRECT="timeout", HTTPS_PROXY=proxy, FAKE_DAEMON_PROXY=proxy,
                        FAKE_MODELS=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"Internet through the proxy {proxy}", run.stdout)

    # ------------------------------------------------------------------ #535: buildx and ZRT's address (HP Z8)

    def test_buildx_as_the_plugin_or_the_standalone_program(self):
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("✓ docker buildx (Docker CLI plugin)", run.stdout)
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FAKE_BUILDX="standalone")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("✓ docker-buildx (standalone program)", run.stdout)
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FAKE_BUILDX="none")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("✗ docker buildx is missing", run.stderr)
        self.assertIn("Run: sudo apt-get install docker-buildx-plugin", run.stderr)
        self.assertIn("(or a standalone docker-buildx on your PATH)", run.stderr)
        # #549: what it tried, and that `docker docker-buildx --version` only printed Docker's own version
        self.assertIn('it printed "Docker version 29.2.1, build a5c7197", Docker\'s own version, not buildx\'s', run.stderr)

    def plugin_dir(self, name: str = "plugins") -> Path:
        """A cli-plugins directory holding a docker-buildx plugin binary (#549), which logs `<its path> <args>`."""
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "docker-buildx").write_text('#!/bin/sh\necho "$0 $*" >> "${FAKE_BUILDX_LOG:-/dev/null}"\n'
                                         'echo "github.com/docker/buildx v0.31.1"\n')
        (d / "docker-buildx").chmod(0o755)
        return d

    def test_build_images_uses_whichever_buildx_works(self):
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        args = ["bash", "infra/deploy/build_images.sh", "--platform", "linux/arm64", "--commit", head, "--api-ref",
                "a:local", "--web-ref", "w:local", "--metadata-dir", str(self.tmp / "meta"), "--load"]
        plugins = self.plugin_dir()
        # #549: also the plugin binary run directly, and `docker docker-buildx` when it answers as buildx
        forms = (("plugin", "docker buildx"), ("standalone", "docker-buildx"), ("dir", f"{plugins}/docker-buildx"),
                 ("docker-cmd", "docker docker-buildx"))
        for kind, program in forms:
            with self.subTest(kind=kind):
                log = self.tmp / f"buildx-{kind}.log"
                run = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60,
                                     env={**self.env, "FAKE_BUILDX": kind, "FAKE_BUILDX_LOG": str(log),
                                          "AWARECARE_DOCKER_PLUGIN_DIRS": f"{self.tmp}/none:{plugins}" if kind == "dir"
                                          else f"{self.tmp}/none"})
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn(f"build_images.sh: using {program} (github.com/docker/buildx", run.stdout)
                builds = [line for line in log.read_text().splitlines() if " build " in line]
                self.assertEqual(len(builds), 2, builds)
                self.assertTrue(all(b.startswith(f"{program} build --platform linux/arm64") for b in builds), builds)
        run = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60,
                             env={**self.env, "FAKE_BUILDX": "none"})
        self.assertEqual(run.returncode, 2)
        self.assertIn("docker buildx is missing", run.stderr)
        self.assertIn("standalone docker-buildx program", run.stderr)

    def zrt_service(self, *ids: str) -> str:
        """A ZRT service's own endpoint: a real HTTP server on a spare loopback port whose /v1/models lists `ids`."""
        import http.server
        import threading
        body = served(*ids).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                code = 200 if self.path == "/v1/models" else 404
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if code == 200:
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.env["FAKE_REAL_CURL"] = shutil.which("curl")
        return f"http://127.0.0.1:{server.server_address[1]}"

    @staticmethod
    def z8_services(endpoint: str) -> str:
        """`zrt services` on the HP Z8 (#535): a GPU column; MODEL URI and SERVED AS in one column over two lines."""
        return "\n".join([
            "┌─────┬───────┬──────────────────────────────────┬───────────────────────┬────────┬────────────────┬────────┐",
            "│ GPU │ PID   │ MODEL URI / SERVED AS            │ API ENDPOINT          │ STATUS │ MEM USAGE      │ UPTIME │",
            "├─────┼───────┼──────────────────────────────────┼───────────────────────┼────────┼────────────────┼────────┤",
            f"│ 0,1 │ 97820 │ hf:{NANO_REPO}@main │ {endpoint} │ Ready  │ 65.3 GB (VRAM) │ 6m ago │",
            f"│     │       │ {NANO_REPO}         │                       │        │                │        │",
            "└─────┴───────┴──────────────────────────────────┴───────────────────────┴────────┴────────────────┴────────┘"])

    def test_a_zrt_service_endpoint_is_found_when_the_proxy_serves_another_model(self):
        endpoint = self.zrt_service(NANO_REPO)
        # #537: the Z8 is its own machine (the generic profile) serving the catalogue model for 64 GB and more
        z8 = {"FAKE_MODELS": served("Prash_0.30.0"), "FAKE_ZRT_SERVICES": self.z8_services(endpoint), **self.machine("z8")}
        run = self.demo("local", "--dry-run", **z8)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Device: HP Z8 Fury G5 Workstation Desktop PC (GPU 2x NVIDIA RTX PRO 5000 72GB Blackwell", run.stdout)
        self.assertIn(f"✓ ZRT serves {NANO_MODEL} as {NANO_REPO} on {endpoint}/v1", run.stdout)
        self.assertIn(f"! ZRT's proxy on 8080 does not list the model; using the service endpoint {endpoint}/v1",
                      run.stdout)
        self.assertIn("can change when the service restarts", run.stdout)
        self.assertIn("serve the model through the proxy", run.stdout)
        deploy = next(line for line in run.stdout.splitlines() if " deploy --mode local" in line)
        self.assertIn(f"--zrt-base-url {endpoint}/v1 ", deploy)
        run = self.demo("status", **z8)
        self.assertIn(f"✓ ZRT serves {NANO_MODEL} as {NANO_REPO} on {endpoint}/v1", run.stdout)
        self.assertIn("using the service endpoint", run.stdout)

    def test_632_the_model_on_another_listening_port_is_found(self):
        """#632: on the shared Fury this account's ZRT proxy was set to 8000 and served nothing; another account's
        ZRT served the model on another loopback port, and this account's `zrt services` listed nothing."""
        endpoint = self.zrt_service(FURY_MODEL)
        port = endpoint.rsplit(":", 1)[1]
        shared = {"FAKE_ZRT_PORT": "8000", "FAKE_PROXY_PORT": "8000", "FAKE_MODELS": served(),
                  "FAKE_GPU": "NVIDIA GB300", "FAKE_LISTEN_PORTS": f"22 8000 {port}"}
        run = self.demo("local", "--dry-run", **shared)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"✓ ZRT serves {FURY_MODEL} on {endpoint}/v1", run.stdout)
        self.assertIn(f"! Nothing on port 8000 lists the model; port {port} serves it (another account's ZRT?), so "
                      f"demo.sh uses {endpoint}/v1", run.stdout)
        self.assertIn("Fix: nothing to do; do not serve it again.", run.stdout)
        self.assertIn(f"--zrt-port {port}", run.stdout)
        self.assertIn(f"--zrt-base-url {endpoint}/v1 ", run.stdout)
        # An address the user named is used as given: no search
        run = self.demo("local", "--dry-run", "--zrt-port", "8000", **shared)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"✗ ZRT does not serve {FURY_MODEL}", run.stderr)
        # A listening port that lists another model is not taken
        other = self.zrt_service("Prash_0.30.0")
        run = self.demo("local", "--dry-run", **{**shared, "FAKE_LISTEN_PORTS": f"8000 {other.rsplit(':', 1)[1]}"})
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("on http://127.0.0.1:8000/v1", run.stderr)

    def test_zrt_url_option_is_used_as_given(self):
        endpoint = self.zrt_service(NANO_MODEL)
        run = self.demo("local", "--dry-run", "--zrt-url", f"{endpoint}/v1/", FAKE_MODELS=served("Prash_0.30.0"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"✓ ZRT serves {NANO_MODEL} on {endpoint}/v1", run.stdout)
        self.assertNotIn("using the service endpoint", run.stdout)
        self.assertIn(f"--zrt-base-url {endpoint}/v1 ", run.stdout)
        # Given, it is not replaced by a service endpoint; the failure names the endpoints and the option.
        other = self.zrt_service("Prash_0.30.0")
        run = self.demo("local", "--dry-run", "--device", "nano", "--zrt-url", f"{other}/v1",
                        FAKE_ZRT_SERVICES=self.z8_services(endpoint))
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"✗ ZRT does not serve {NANO_MODEL} ({NANO_REPO}, any revision) on {other}/v1", run.stderr)
        self.assertIn("ZRT serves: Prash_0.30.0", run.stderr)
        self.assertIn(f"zrt services lists: {endpoint} ({NANO_REPO}, Ready, this model)", run.stderr)
        self.assertIn("ZRT serves it on another port? $ ./demo.sh local --zrt-port <port>", run.stderr)
        for bad in ("http://192.0.2.1:9093/v1", "https://127.0.0.1:9093/v1", "http://127.0.0.1:9093@evil/v1"):
            with self.subTest(url=bad):
                run = self.demo("local", "--dry-run", "--zrt-url", bad)
                self.assertEqual(run.returncode, 2)
                self.assertIn("must be ZRT on this device", run.stderr)

    def test_the_nanos_table_without_an_endpoint_keeps_the_proxy(self):
        nano = (f"│ PID    │ MODEL URI                         │ SERVED AS           │ API ENDPOINT │ STATUS │ MEM USAGE      │ UPTIME │\n"
                f"│ 129042 │ hf:{NANO_REPO}@95a7… │ {NANO_MODEL} │ -            │ Ready  │ 47.0 GB (VRAM) │ 4d ago │")
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FAKE_ZRT_SERVICES=nano)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"✓ ZRT serves {NANO_MODEL} on http://127.0.0.1:8080/v1", run.stdout)
        self.assertNotIn("service endpoint", run.stdout)
        self.assertIn("--zrt-base-url http://127.0.0.1:8080/v1 ", run.stdout)
        # Not on the proxy either: nothing to discover (no endpoint), so it fails on the proxy URL and names the row.
        run = self.demo("local", "--dry-run", "--device", "nano", FAKE_MODELS=served("Prash_0.30.0"),
                        FAKE_ZRT_SERVICES=nano)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"on http://127.0.0.1:8080/v1", run.stderr)
        self.assertIn(f"zrt services lists: - ({NANO_MODEL}, Ready, this model)", run.stderr)

    # ------------------------------------------------------------------ what local runs

    def test_local_dry_run_prints_build_key_and_deploy(self):
        run = self.demo("local", "--dry-run", "--port", "28180", FAKE_MODELS=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        out = run.stdout
        self.assertEqual(out.splitlines()[0], "Aware Care · local mode on HP ZGX Nano · dry run")
        self.assertIn(f"commit {head[:12]}", out.splitlines()[1])
        lines = [line.strip()[2:] for line in out.splitlines() if line.strip().startswith("$ ")]
        self.assertEqual(len(lines), 4, out)
        build, key, deploy, sampler = lines
        # #678: then the power sampler's step for this data root
        self.assertEqual(sampler, f"python3 infra/deploy/nano_deploy.py --data-root {self.tmp}/home/.local/share/"
                                  "aware-care-demo power-sampler")
        self.assertTrue(build.startswith("infra/deploy/build_images.sh --platform linux/arm64"), build)
        self.assertIn(f"--commit {head}", build)
        self.assertTrue(build.endswith("--load"), build)
        self.assertIn("--config infra/deploy/demo-zgx-nano.json --zrt-base-url http://127.0.0.1:8080/v1 "
                      "--origin http://127.0.0.1:28180 presenter-key", key)
        self.assertIn(f"deploy --mode local --model-id {NANO_MODEL} --release-tag ", deploy)
        self.assertIn(f"--app-commit {head}", deploy)
        self.assertIn("--no-pull --allow-unpinned", deploy)
        self.assertIn("ssh -N -p 2222 -L 28180:127.0.0.1:8180 alice@192.0.2.3", out)
        self.assertIn("http://127.0.0.1:28180", out)
        self.assertNotIn("gh workflow", out)

    def test_a_scratch_instance_gets_its_own_names_data_and_ports(self):
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), AWARECARE_DEMO_INSTANCE="scratch",
                        AWARECARE_DEMO_DATA_ROOT="/tmp/scratch-root", AWARECARE_DEMO_API_PORT="28100",
                        AWARECARE_DEMO_WEB_PORT="28181")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--zrt-base-url http://127.0.0.1:8080/v1 --instance scratch --data-root /tmp/scratch-root "
                      "--api-port 28100 --web-port 28181 deploy",
                      run.stdout)
        self.assertIn("--api-image scratch-api:local --web-image scratch-web:local", run.stdout)
        self.assertIn("-L 18180:127.0.0.1:28181", run.stdout)

    # ------------------------------------------------------------------ #644: no main instance

    RELEASE = "ghcr.io/your-github-user/aware-care/aware-care-api@sha256:" + "a" * 64

    def bob(self) -> dict[str, str]:
        """bob's ./demo.sh instance: the same container names, images built by demo.sh, data in bob's home."""
        return {"FAKE_RUNNING_IMAGE": "aware-care-demo-api:local", "FAKE_MODELS": served(NANO_MODEL),
                "FAKE_DATA_MOUNT": "/home/bob/.local/share/aware-care-demo/data/local"}

    def test_632_644_local_and_setup_beside_a_running_demo_say_whose_it_is_and_exit_0(self):
        """#632: a second account on the Fury ran local beside the maintainer's release. #644: there is no main
        instance: beside anyone's running demo, local and setup say whose it is, whether it answers ready, how to open
        it and how to replace it (--replace), and exit 0 without building, deploying or removing anything."""
        log = self.tmp / "docker.log"
        cases = {"release": ({"FAKE_RUNNING_IMAGE": self.RELEASE, "FAKE_MODELS": served(NANO_MODEL),
                              "FAKE_RELEASE": "v0.19.0-demo.1"},
                             "the release v0.19.0-demo.1 from the deploy workflow"),
                 "bob": (self.bob(), "the ./demo.sh instance of bob"),
                 "own elsewhere": ({**self.bob(), "FAKE_DATA_MOUNT": f"{self.tmp}/home/old-root/data/local",
                                    "FAKE_OWNER_OF": f"{self.tmp}/home/old-root=alice"},
                                   f"your own instance with its data in {self.tmp}/home/old-root")}
        self.fake_stat()
        for name, (env, whose) in cases.items():
            for cmd in ("local", "setup"):
                for ready in ("1", ""):
                    with self.subTest(case=name, cmd=cmd, ready=ready):
                        run = self.demo(cmd, "--no-color", FAKE_DOCKER_LOG=str(log), FAKE_READY=ready,
                                        **self.machine("gb10"), **env,
                                        FAKE_WEB_ENV=',"AWARECARE_WEB_PORT=8180","AWARECARE_ORIGIN=http://127.0.0.1:18180"')
                        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                        # #696 (T3): "It's already running: open it here", whose it is, the way in; --replace is
                        # not pushed
                        self.assertIn("✓ It's already running: open it here\n"
                                      f"    {whose[0].upper() + whose[1:]} (aware-care-demo-api, aware-care-demo-web)\n",
                                      run.stdout)
                        self.assertIn("✓ It answers ready on 127.0.0.1:8180" if ready else
                                      "! It does not answer on 127.0.0.1:8180 yet", run.stdout)
                        self.assertIn("ssh -N -p 2222 -L 18180:127.0.0.1:8180 alice@192.0.2.3", run.stdout)
                        self.assertIn("Then open:  http://127.0.0.1:18180", run.stdout)
                        self.assertNotIn("--replace", run.stdout)
                        self.assertIn('Your own copy instead: README, "Several people on one machine".', run.stdout)
                        self.assertNotIn("build_images.sh", run.stdout)
                        self.assertNotIn("\nModel\n", run.stdout.split("Already running")[1])
        self.assertFalse(log.exists(), "nothing may be built, deployed or removed")

    def fake_stat(self) -> None:
        """#644: `stat -c %U <path>` answers FAKE_OWNER_OF ("<path>=<user>") for that path, else the real stat."""
        stat = self.tmp / "bin/stat"
        stat.write_text('#!/bin/sh\nif [ "$1 $2" = "-c %U" ] && [ -n "${FAKE_OWNER_OF:-}" ]; then\n'
                        '  for a in "$@"; do [ "$a" = "${FAKE_OWNER_OF%%=*}" ] && { echo "${FAKE_OWNER_OF#*=}"; exit 0; }; done\n'
                        f'fi\nexec {shutil.which("stat")} "$@"\n')
        stat.chmod(0o755)

    def test_644_replace_says_what_happens_then_removes_the_running_containers_after_the_build(self):
        log = self.tmp / "docker.log"
        run = self.demo("local", "--replace", "--dry-run", "--no-color", FAKE_DOCKER_LOG=str(log), **self.bob())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = run.stdout
        self.assertIn("! --replace: aware-care-demo-api and aware-care-demo-web run the ./demo.sh instance of bob", out)
        self.assertIn("Its containers are removed just before your deploy; its data stays in "
                      "/home/bob/.local/share/aware-care-demo (nothing of it is deleted).", out)
        order = ["--replace: aware-care-demo-api", "build_images.sh", "$ docker rm -f aware-care-demo-api aware-care-demo-web",
                 "nano_deploy.py", "deploy --mode local"]
        positions = [out.index(step) for step in order]
        self.assertEqual(positions, sorted(positions), out)
        self.assertNotIn("Already running", out)
        self.assertFalse(log.exists(), "a dry run removes nothing")
        # a real setup --replace: removes the containers after the build, then deploys
        repo = self.setup_clone()
        run = self.demo("setup", "--replace", "--no-color", script=repo / "demo.sh", FAKE_DOCKER_LOG=str(log),
                        **{**self.machine("z8"), **self.bob(), "FAKE_MODELS": served(NANO_MODEL)})
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("docker rm -f aware-care-demo-api aware-care-demo-web", log.read_text())
        self.assertIn("✓ Removed aware-care-demo-api and aware-care-demo-web (the ./demo.sh instance of bob); its data "
                      "stays in /home/bob/.local/share/aware-care-demo", run.stdout)
        self.assertIn("build_images.sh", self.log("build.log"))
        self.assertIn("deploy", self.log("deploy.log").split())
        # with nothing running, --replace just deploys
        log.unlink()
        run = self.demo("local", "--replace", "--dry-run", FAKE_DOCKER_LOG=str(log), FAKE_MODELS=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("docker rm", run.stdout)
        self.assertNotIn("--replace:", run.stdout)
        self.assertIn("deploy --mode local", run.stdout)
        for args in (("stop", "--replace"), ("model", "--replace"), ("setup", "--mock", "--replace")):
            self.assertEqual(self.demo(*args).returncode, 2, args)

    def test_644_stop_and_uninstall_remove_anyones_containers_and_never_their_data(self):
        """#644: stop, uninstall and uninstall --all never refuse because of whose demo runs (#617, #634, #636 refused);
        they remove the containers, and only paths of your own data root are deleted."""
        log = self.tmp / "docker.log"
        for env, whose, kept in ((self.bob(), "the ./demo.sh instance of bob",
                                  "its data stays in /home/bob/.local/share/aware-care-demo"),
                                 ({"FAKE_RUNNING_IMAGE": self.RELEASE, "FAKE_RELEASE": "v0.19.4-demo.1"},
                                  "the release v0.19.4-demo.1 from the deploy workflow", "its data stays where it is")):
            for args in (("stop",), ("stop", "local")):
                with self.subTest(args=args, whose=whose):
                    log.unlink(missing_ok=True)
                    run = self.demo(*args, "--no-color", FAKE_DOCKER_LOG=str(log), **env)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn("rm -f aware-care-demo-api", log.read_text())
                    self.assertIn(f"✓ Stopped aware-care-demo-api and aware-care-demo-web ({whose}; {kept})", run.stdout)
        repo = self.tree()
        root = self.tmp / "home/.local/share/aware-care-demo"
        (root / "state").mkdir(parents=True)
        (root / "state/current.json").write_text(f'{{"api_image": "{self.RELEASE}"}}\n')
        for args in (("uninstall", "--yes"), ("uninstall", "--all", "--yes")):
            with self.subTest(args=args):
                (root / "state").mkdir(parents=True, exist_ok=True)
                log.unlink(missing_ok=True)
                run = self.demo(*args, "--no-color", script=repo / "demo.sh", FAKE_DOCKER_LOG=str(log), **self.bob())
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("✓ Removed the containers aware-care-demo-api aware-care-demo-web (the ./demo.sh instance "
                              "of bob; its data stays in /home/bob/.local/share/aware-care-demo)", run.stdout)
                self.assertIn("rm -f aware-care-demo-api aware-care-demo-web", log.read_text())
                self.assertFalse(root.exists(), "your own data root goes")
                self.assertNotIn("refused", run.stdout + run.stderr)

    def test_644_uninstall_never_deletes_a_data_root_of_another_account(self):
        theirs = self.tmp / "bob-root"
        (theirs / "state").mkdir(parents=True)
        self.fake_stat()
        for args in (("uninstall", "--dry-run"), ("uninstall", "--yes")):
            run = self.demo(*args, "--instance", "scratch", AWARECARE_DEMO_DATA_ROOT=str(theirs),
                            FAKE_OWNER_OF=f"{theirs}=bob")
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn(f"Kept: {theirs} (the app's data, presenter key and backups) belongs to bob, not to you",
                          run.stdout)
            self.assertTrue((theirs / "state").exists())
        run = self.demo("uninstall", "--yes", "--instance", "scratch", AWARECARE_DEMO_DATA_ROOT=str(theirs))
        self.assertFalse(theirs.exists(), "your own goes")

    def test_a_deployment_demo_sh_built_is_stopped(self):
        log = self.tmp / "docker.log"
        run = self.demo("stop", "local", FAKE_RUNNING_IMAGE="aware-care-demo-api:local", FAKE_DOCKER_LOG=str(log))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("rm -f aware-care-demo-api", log.read_text())
        self.assertIn("Stopped aware-care-demo-api and aware-care-demo-web (data kept in", run.stdout)

    def test_590_a_stop_whose_container_removal_fails_names_it_and_fails(self):
        """#590: docker rm failing for both, only the API or only the web container: exit 1, the container still
        running named, and only the ones really removed reported as stopped (never "No ... containers")."""
        api, web = "aware-care-demo-api", "aware-care-demo-web"
        for failing in ((api, web), (api,), (web,)):
            with self.subTest(failing=failing):
                log = self.tmp / "docker.log"
                log.unlink(missing_ok=True)
                run = self.demo("stop", "local", "--no-color", FAKE_RUNNING_IMAGE="aware-care-demo-api:local",
                                FAKE_DOCKER_LOG=str(log), FAKE_RM_FAIL=" ".join(failing))
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertEqual(log.read_text().count("docker rm -f"), 2, "both removals are tried")
                self.assertNotIn("No aware-care-demo containers", run.stdout)
                self.assertIn(f"Could not stop {' and '.join(failing)}", run.stderr)
                stopped = [n for n in (api, web) if n not in failing]
                stop_lines = [line for line in run.stdout.splitlines() if "Stopped" in line]
                if stopped:
                    self.assertEqual(len(stop_lines), 1, run.stdout)
                    self.assertIn(f"Stopped {stopped[0]} (data kept in", stop_lines[0])
                    self.assertNotIn(failing[0], stop_lines[0])
                else:
                    self.assertEqual(stop_lines, [], run.stdout)

    # ------------------------------------------------------------------ update

    def test_update_refuses_a_checkout_with_local_changes(self):
        repo = self.tmp / "clone"
        repo.mkdir()
        shutil.copy(SCRIPT, repo / "demo.sh")
        (repo / "notes.txt").write_text("one\n")
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        for cmd in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-qm", "one"], ["tag", "v1.0.0"]):
            subprocess.run([*git, *cmd], check=True, capture_output=True)
        (repo / "notes.txt").write_text("two\n")
        before = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        run = self.demo("update", "v1.0.0", script=repo / "demo.sh")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("local changes", run.stderr)
        self.assertIn("git -C", run.stderr)
        self.assertEqual(subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout, before)
        self.assertEqual((repo / "notes.txt").read_text(), "two\n")

    def test_help_lists_every_command(self):
        run = self.demo("--help")
        self.assertEqual(run.returncode, 0)
        for word in ("setup", "--mock", "--rebuild", "--zrt-port", "mock", "local", "model", "status", "update", "stop",
                     "uninstall", "open", "fresh", "--port", "--dry-run",
                     "--revision", "--no-color", "doctor", "check-model", "--model <label>", "--zrt-mode user|system",
                     "--device nano|fury|auto", "--instance", "--api-port", "--web-port", "--all", "--with-model",
                     "--yes", "AWARECARE_DEMO_INSTANCE", "AWARECARE_DEMO_DATA_ROOT", "AWARECARE_DEMO_API_PORT",
                     "AWARECARE_DEMO_WEB_PORT"):
            self.assertIn(word, run.stdout)
        # The commands form an aligned table: every description starts in the same column.
        lines = run.stdout.split("Commands\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(len(lines), 12, run.stdout)
        self.assertEqual(len({re.match(r"  \S.*?\s{2,}(\S)", line).start(1) for line in lines}), 1, lines)

    # ------------------------------------------------------------------ QA repl-01: --dry-run never changes anything

    def recording(self) -> dict[str, str]:
        """The stand-ins' logs of every call that would change something."""
        return {"FAKE_DOCKER_LOG": str(self.tmp / "docker.log"), "FAKE_SYSTEMCTL_LOG": str(self.tmp / "systemctl.log"),
                "FAKE_TOOL_LOG": str(self.tmp / "tools.log")}

    def changes(self) -> str:
        """What the stand-ins recorded as changes: docker, systemctl, uv/npm installs and starts, zrt pull/remove/serve."""
        out = [(self.tmp / n).read_text() for n in ("docker.log", "systemctl.log", "tools.log") if (self.tmp / n).exists()]
        out += [line + "\n" for line in self.zrt_calls().splitlines()
                if re.match(r"zrt (pull|remove|service (start|stop))", line)]
        return "".join(out)

    def tree(self) -> Path:
        """A copy of what demo.sh reads, so that a real run's checkout is a scratch directory, never this one."""
        repo = self.tmp / "clone"
        for rel in ("demo.sh", "apps/api/app/runtime/model_ids.py", "apps/web/package-lock.json",
                    "infra/deploy/demo-zgx-nano.json", "infra/deploy/demo-zgx-fury.json"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, repo / rel)
        for rel in ("infra/nano/zrt", "infra/fury/zrt", "infra/zrt"):
            shutil.copytree(ROOT / rel, repo / rel)
        (repo / "apps/web/node_modules").symlink_to(self.tmp)  # a link: mock never reinstalls it
        return repo

    def installed(self, instance: str = "aware-care-demo") -> list[Path]:
        """What demo.sh installs for a user: data root, model unit, serve script, settings, logs, mock data."""
        home = self.tmp / "home"
        paths = [home / f".local/share/{instance}/state/current.json",
                 home / ".local/share/aware-care-demo/zrt/serve-model.sh",
                 home / ".config/systemd/user/aware-care-zrt-model.service",
                 home / ".config/aware-care-demo/model.env", self.tmp / "logs/api.log"]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("AWARECARE_MODEL_REVISION=main\n" if path.name == "model.env" else "x\n")
        return paths

    def test_dry_run_of_mock_local_model_status_doctor_and_check_model_changes_nothing(self):
        for args in (("mock",), ("local",), ("model", "--device", "nano"), ("status",), ("doctor",), ("check-model",)):
            with self.subTest(args=args):
                run = self.demo(*args, "--dry-run", FAKE_MODELS=served("Qwen/Qwen3-32B") if args[0] == "model"
                                else served(NANO_MODEL), FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"),
                                **self.recording())
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual(self.changes(), "")
                self.assertEqual([p for p in (self.tmp / "logs").glob("check-model-*") if p.suffix != ".log"], [],
                                 "a dry run writes no report")
        self.assertFalse((self.tmp / "home").exists(), "a dry run installs nothing")

    def test_dry_run_of_stop_kills_and_removes_nothing(self):
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        state = self.tmp / "logs/mock.state"
        state.parent.mkdir(parents=True)
        state.write_text(f"API_PID={proc.pid}\nWEB_PID={proc.pid}\nAPI_PORT=8000\nWEB_PORT=5173\nBROWSER_PORT=15173\n")
        run = self.demo("stop", "--dry-run", **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"kill -TERM -- -{proc.pid}", run.stdout)
        time.sleep(0.3)
        self.assertIsNone(proc.poll(), "a dry run kills nothing")
        self.assertTrue(state.exists())
        run = self.demo("stop", "local", "--dry-run", FAKE_RUNNING_IMAGE="aware-care-demo-api:local", **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("$ docker rm -f aware-care-demo-api", run.stdout)
        self.assertIn("Dry run: nothing was stopped.", run.stdout)
        self.assertEqual(self.changes(), "")

    def test_dry_run_of_uninstall_removes_nothing(self):
        repo = self.tree()
        (repo / "runtime-data/api").mkdir(parents=True)
        paths = self.installed()
        images = "aware-care-demo-api:local aware-care-demo-web:local aware-care-api:local aware-care-web:local"
        for args in (("--yes",), ("--all", "--with-model", "--yes"), ("--all",)):
            with self.subTest(args=args):
                run = self.demo("uninstall", "--dry-run", *args, script=repo / "demo.sh", FAKE_IMAGES=images,
                                FAKE_RUNNING_IMAGE="aware-care-demo-api:local",
                                FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"), **self.recording())
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("Dry run: nothing was removed.", run.stdout)
                self.assertIn("$ docker rm -f aware-care-demo-api aware-care-demo-web", run.stdout)
                self.assertEqual(self.changes(), "")
                if "--with-model" in args:
                    self.assertIn(f"$ zrt -m system remove hf:{NANO_REPO}@main", run.stdout)
                for path in [*paths, repo / "runtime-data/api"]:
                    self.assertTrue(path.exists(), path)

    def git_repo(self, *steps: tuple[str, bool]) -> tuple[Path, list[str]]:
        """A clone whose origin is itself; each step is a commit (with or without demo.sh) and a tag v0.<n>.0."""
        repo = self.tmp / "clone"
        repo.mkdir()
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
        for n, (text, with_script) in enumerate(steps):
            (repo / "notes.txt").write_text(text)
            if with_script:
                shutil.copy(SCRIPT, repo / "demo.sh")
            for cmd in (["add", "."], ["commit", "-qm", text], ["tag", f"v0.{n}.0"]):
                subprocess.run([*git, *cmd], check=True, capture_output=True)
        subprocess.run([*git, "remote", "add", "origin", str(repo)], check=True)
        return repo, git

    def test_dry_run_of_update_fetches_and_checks_out_nothing(self):
        repo, git = self.git_repo(("one", True), ("two", True))
        subprocess.run([*git, "-c", "advice.detachedHead=false", "checkout", "-q", "v0.0.0"], check=True)
        origin = self.tmp / "origin"
        subprocess.run(["git", "clone", "-q", str(repo), str(origin)], check=True)
        subprocess.run(["git", "-C", str(origin), "tag", "v0.9.0"], check=True)  # only a fetch would bring it
        subprocess.run([*git, "remote", "set-url", "origin", str(origin)], check=True)
        before = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        run = self.demo("update", "--dry-run", script=repo / "demo.sh", **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("fetch --tags --quiet origin", run.stdout)
        self.assertIn("checkout v0.1.0", run.stdout)
        self.assertIn("Dry run: nothing was fetched, checked out or restarted.", run.stdout)
        self.assertEqual(subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout, before)
        self.assertNotIn("v0.9.0", subprocess.run([*git, "tag"], capture_output=True, text=True).stdout)

    # ------------------------------------------------------------------ QA repl-04: update to a release without demo.sh

    def test_update_refuses_a_tag_without_demo_sh_before_the_checkout(self):
        repo, git = self.git_repo(("old", False), ("new", True))
        before = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        for extra in ((), ("--dry-run",)):
            with self.subTest(extra=extra):
                run = self.demo("update", "v0.0.0", *extra, script=repo / "demo.sh")
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn("v0.0.0 is older than demo.sh (it has no demo.sh)", run.stderr)
                self.assertIn("tag -l 'v*'", run.stderr)
                self.assertEqual(subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout,
                                 before)
                self.assertTrue((repo / "demo.sh").exists())

    # ------------------------------------------------------------------ #640: the model's watchdog

    def watchdog(self, device: str = "nano", **env: str) -> subprocess.CompletedProcess:
        """One run of the installed watchdog (infra/zrt/model-watchdog.sh beside the device's serve script), with a
        model unit that is enabled, active for an hour and whose model ZRT does not list, unless env says otherwise."""
        zrt = self.tmp / "home/.local/share/aware-care-demo/zrt"
        zrt.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "infra/zrt/model-watchdog.sh", zrt / "model-watchdog.sh")
        shutil.copy(ROOT / f"infra/{device}/zrt/serve-model.sh", zrt / "serve-model.sh")
        defaults = dict(FAKE_ENABLED="enabled", FAKE_ACTIVE="active", FAKE_ENTERED="2020-01-01 00:00:00 UTC",
                        FAKE_SYSTEMCTL_LOG=str(self.tmp / "systemctl.log"))
        return subprocess.run(["bash", str(zrt / "model-watchdog.sh")], env={**self.env, **defaults, **env},
                              capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)

    def restarts(self) -> list[str]:
        log = self.tmp / "systemctl.log"
        return [line for line in (log.read_text().splitlines() if log.exists() else []) if " restart " in line]

    @property
    def wd_state(self) -> Path:
        return self.tmp / "home/.local/share/aware-care-demo/zrt/watchdog.state"

    @staticmethod
    def service_rows(pid: int, status: str = "Dead") -> str:
        """`zrt services` with the Nano's model in ZRT 0.43's layout (the served name on a continuation line)."""
        return "\n".join([
            "│ GPU │ PID     │ MODEL URI / SERVED AS │ API ENDPOINT          │ STATUS │ MEM USAGE │ UPTIME │",
            f"│ 0   │ {pid} │ hf:{NANO_REPO}@{NANO_PINNED} │ http://127.0.0.1:8080 │ {status} │ 46.2 GB (VRAM) │ 3m ago │",
            f"│     │         │ {NANO_MODEL} │                       │        │           │        │"])

    @staticmethod
    def dead_pid() -> int:
        proc = subprocess.Popen(["true"])
        proc.wait()
        return proc.pid

    def test_watchdog_restarts_the_unit_when_the_model_died(self):
        run = self.watchdog(FAKE_ZRT_SERVICES=self.service_rows(self.dead_pid()))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"watchdog: {NANO_MODEL} is not served and no ZRT service process for it is alive; restarting "
                      "aware-care-zrt-model.service (restart 1 of 3 within an hour)", run.stdout)
        self.assertEqual(self.restarts(), ["systemctl --user restart --no-block aware-care-zrt-model.service"])
        self.assertRegex(self.wd_state.read_text(), r"^restart \d+\n$")
        # no ZRT service at all (a ZRT reinstall): the same
        run = self.watchdog(FAKE_ZRT_SERVICES="")
        self.assertIn("restart 2 of 3", run.stdout)
        # a generic machine: the model and its label from model.env
        run = self.watchdog("generic", AWARECARE_MODEL_URI="hf:Qwen/Qwen3-14B-FP8@abc", AWARECARE_MODEL_LABEL="qwen3-14b-fp8",
                            FAKE_MODELS=served("Qwen/Qwen3-14B-FP8@main"))
        self.assertIn("watchdog: qwen3-14b-fp8 is served; nothing to do", run.stdout)

    def test_watchdog_never_starts_a_unit_stopped_on_purpose(self):
        for enabled, active in (("enabled", "inactive"), ("disabled", "inactive"), ("disabled", "active"),
                                ("enabled", "failed"), ("enabled", "activating"), ("", "inactive")):
            with self.subTest(enabled=enabled, active=active):
                run = self.watchdog(FAKE_ENABLED=enabled, FAKE_ACTIVE=active)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn("not meant to run (or starting); leaving it", run.stdout)
        self.assertEqual(self.restarts(), [])
        self.assertFalse(self.wd_state.exists())

    def test_watchdog_leaves_a_served_or_loading_model_alone(self):
        cases = {
            "served": (dict(FAKE_MODELS=served(f"{NANO_REPO}@main")), f"{NANO_MODEL} is served; nothing to do"),
            "process alive": (dict(FAKE_ZRT_SERVICES=self.service_rows(os.getpid())),
                              f"its ZRT service process {os.getpid()} is alive (loading?); waiting"),
            "just started": (dict(FAKE_ENTERED=time.strftime("%Y-%m-%d %H:%M:%S %Z")), "started less than 300s ago"),
            "zrt does not answer": (dict(FAKE_ZRT_DOWN="1"), "zrt services does not answer; waiting"),
        }
        for name, (env, says) in cases.items():
            with self.subTest(name):
                run = self.watchdog(**env)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn(says, run.stdout)
        self.assertEqual(self.restarts(), [])

    def test_watchdog_gives_up_after_three_restarts_within_an_hour(self):
        now = int(time.time())
        self.watchdog(FAKE_ACTIVE="inactive")  # installs the script
        self.wd_state.write_text(f"restart {now - 4000}\nrestart {now - 1800}\nrestart {now - 600}\n")
        run = self.watchdog()  # the one over an hour ago does not count
        self.assertIn("restart 3 of 3", run.stdout)
        run = self.watchdog()
        self.assertIn("is not served after 3 restarts within an hour; giving up", run.stdout)
        run = self.watchdog()
        self.assertIn("gave up earlier (3 restarts within an hour): run ./demo.sh model", run.stdout)
        self.assertEqual(len(self.restarts()), 1)
        # served again (someone started it): restarts are allowed again, and its restarts still count for the hour
        run = self.watchdog(FAKE_MODELS=served(NANO_MODEL))
        self.assertIn("is served again; restarts allowed again", run.stdout)
        self.assertIn("giving up", self.watchdog().stdout)
        self.assertEqual(len(self.restarts()), 1)

    def test_model_installs_and_starts_the_watchdog_with_the_unit(self):
        dry = self.model_run("--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        home = self.tmp / "home"
        for line in (f"install -D -m 755 infra/zrt/model-watchdog.sh {home}/.local/share/aware-care-demo/zrt/model-watchdog.sh",
                     f"install -D -m 644 infra/nano/zrt/aware-care-zrt-watchdog.service {home}/.config/systemd/user/aware-care-zrt-watchdog.service",
                     f"install -D -m 644 infra/nano/zrt/aware-care-zrt-watchdog.timer {home}/.config/systemd/user/aware-care-zrt-watchdog.timer",
                     f"rm -f {home}/.local/share/aware-care-demo/zrt/watchdog.state",
                     "systemctl --user enable --now aware-care-zrt-watchdog.timer"):
            self.assertIn(line, dry.stdout)
        self.assertFalse(home.exists(), "a dry run installs nothing")

        run = self.model_run(FAKE_MODELS_AFTER=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Watchdog on: aware-care-zrt-watchdog.timer restarts aware-care-zrt-model.service when the model "
                      "dies", run.stdout)
        calls = (self.tmp / "systemctl.log").read_text()
        self.assertLess(calls.index("restart --no-block aware-care-zrt-model.service"),
                        calls.index("enable --now aware-care-zrt-watchdog.timer"))
        self.assertTrue(os.access(home / ".local/share/aware-care-demo/zrt/model-watchdog.sh", os.X_OK))
        timer = (home / ".config/systemd/user/aware-care-zrt-watchdog.timer").read_text()
        self.assertIn("OnCalendar=minutely", timer)
        service = (home / ".config/systemd/user/aware-care-zrt-watchdog.service").read_text()
        self.assertIn("ExecStart=%h/.local/share/aware-care-demo/zrt/model-watchdog.sh", service)
        self.assertIn("EnvironmentFile=-%h/.config/aware-care-demo/model.env", service)

    def test_model_adds_the_watchdog_to_a_unit_that_already_serves(self):
        run = self.model_run(FAKE_MODELS=served(NANO_MODEL))  # no unit installed: nothing to watch
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("Watchdog", run.stdout)
        unit = self.tmp / "home/.config/systemd/user/aware-care-zrt-model.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("x\n")
        self.wd_state.parent.mkdir(parents=True)
        self.wd_state.write_text("gaveup 1\n")
        run = self.model_run(FAKE_MODELS=served(NANO_MODEL), FAKE_ENABLED="enabled")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ZRT already serves", run.stdout)
        self.assertIn("Watchdog on:", run.stdout.split("\nWatchdog\n")[1])
        self.assertIn("systemctl --user enable --now aware-care-zrt-watchdog.timer",
                      (self.tmp / "systemctl.log").read_text())
        self.assertFalse(self.wd_state.exists(), "a person ran model: a fresh restart count")
        self.assertTrue((self.tmp / "home/.config/systemd/user/aware-care-zrt-watchdog.timer").exists())
        # installed as this checkout has it and on: a rerun changes nothing
        (self.tmp / "systemctl.log").unlink()
        run = self.model_run(FAKE_MODELS=served(NANO_MODEL), FAKE_WD_TIMER="on", FAKE_ENABLED="enabled")
        self.assertNotIn("Watchdog", run.stdout)
        self.assertFalse((self.tmp / "systemctl.log").exists())

    def test_status_and_doctor_show_the_watchdog(self):
        for command in ("status", "doctor"):
            with self.subTest(command):
                run = self.demo(command, FAKE_MODELS=served(NANO_MODEL))
                self.assertIn("Watchdog: off (./demo.sh model turns it on", run.stdout)
                run = self.demo(command, FAKE_MODELS=served(NANO_MODEL), FAKE_WD_TIMER="on")
                self.assertIn("✓ Watchdog: on (restarts the model unit when the model dies; no restart yet)", run.stdout)
                self.wd_state.parent.mkdir(parents=True, exist_ok=True)
                self.wd_state.write_text("restart 1793134110\n")
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(1793134110))
                run = self.demo(command, FAKE_MODELS=served(NANO_MODEL), FAKE_WD_TIMER="on")
                self.assertIn(f"✓ Watchdog: on (restarts the model unit when the model dies; last restart {when})",
                              run.stdout)
                self.wd_state.write_text("restart 1793134110\ngaveup 1793134170\n")
                run = self.demo(command, FAKE_MODELS=served(NANO_MODEL), FAKE_WD_TIMER="on")
                self.assertIn(f"! Watchdog: on, but it gave up after 3 restarts within an hour (last restart {when})\n"
                              "    Fix: ./demo.sh model serves the model again", run.stdout)
                self.wd_state.unlink()

    def test_uninstall_removes_the_watchdog_before_the_unit(self):
        home = self.tmp / "home"
        files = [home / ".config/systemd/user/aware-care-zrt-watchdog.timer",
                 home / ".config/systemd/user/aware-care-zrt-watchdog.service",
                 home / ".config/systemd/user/aware-care-zrt-model.service",
                 home / ".local/share/aware-care-demo/zrt/model-watchdog.sh", self.wd_state]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n")
        log = self.tmp / "systemctl.log"
        dry = self.demo("uninstall", "--dry-run", FAKE_SYSTEMCTL_LOG=str(log))
        self.assertIn("- the model watchdog aware-care-zrt-watchdog.timer and aware-care-zrt-watchdog.service", dry.stdout)
        self.assertIn("systemctl --user disable --now aware-care-zrt-watchdog.timer", dry.stdout)
        self.assertTrue(all(path.exists() for path in files))
        run = self.demo("uninstall", "--yes", FAKE_SYSTEMCTL_LOG=str(log))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("✓ Removed the model watchdog aware-care-zrt-watchdog.timer", run.stdout)
        calls = log.read_text()
        self.assertLess(calls.index("disable --now aware-care-zrt-watchdog.timer"),
                        calls.index("disable --now aware-care-zrt-model.service"))
        for path in files:
            self.assertFalse(path.exists(), path)

    # ------------------------------------------------------------------ uninstall --all

    def test_uninstall_all_removes_everything_demo_sh_added_and_says_what_stays(self):
        repo = self.tree()
        (repo / "runtime-data/api").mkdir(parents=True)
        paths = self.installed()
        keep = [self.tmp / "home/.local/share/other-app/data", self.tmp / "home/.config/other/settings"]
        for path in keep:
            path.parent.mkdir(parents=True)
            path.write_text("keep\n")
        calls = self.tmp / "calls.log"  # systemctl and zrt in one log, to see the order
        env = dict(FAKE_IMAGES="aware-care-demo-api:local aware-care-demo-web:local aware-care-api:local "
                               "aware-care-web:local other:latest",
                   FAKE_RUNNING_IMAGE="aware-care-demo-api:local", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"),
                   FAKE_DOCKER_LOG=str(self.tmp / "docker.log"), FAKE_SYSTEMCTL_LOG=str(calls), FAKE_ZRT_LOG=str(calls))
        asked = self.demo("uninstall", "--all", "--with-model", script=repo / "demo.sh", **env)
        self.assertIn("Nothing changed.", asked.stdout)  # no answer, no change
        self.assertTrue(all(path.exists() for path in paths))
        run = self.demo("uninstall", "--all", "--with-model", "--yes", script=repo / "demo.sh", **env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        docker = (self.tmp / "docker.log").read_text()
        self.assertIn("docker rm -f aware-care-demo-api aware-care-demo-web", docker)
        for image in ("aware-care-demo-api:local", "aware-care-demo-web:local", "aware-care-api:local",
                      "aware-care-web:local"):
            self.assertIn(f"docker image rm {image}", docker)
        self.assertNotIn("other:latest", docker)
        log = calls.read_text()
        self.assertIn("systemctl --user disable --now aware-care-zrt-model.service", log)
        self.assertIn(f"zrt -m system remove hf:{NANO_REPO}@main", log)
        self.assertLess(log.index("disable --now"), log.index("zrt -m system services"), "the unit stops before the check")
        self.assertLess(log.index("zrt -m system services"), log.index("zrt -m system remove"))
        for path in [*paths, repo / "runtime-data/api", self.tmp / "home/.local/share/aware-care-demo",
                     self.tmp / "home/.config/aware-care-demo", self.tmp / "logs"]:
            self.assertFalse(path.exists(), path)
        for path in keep:
            self.assertTrue(path.exists(), path)
        self.assertTrue((repo / "demo.sh").exists(), "the checkout stays")
        stays = run.stdout.split("What stays")[1]
        self.assertIn(f"cd ~ && rm -rf {repo}", stays)
        for word in ("Docker", "ZRT"):
            self.assertIn(word, stays)
        self.assertNotIn("--with-model", stays)

    def test_uninstall_all_keeps_a_model_that_something_else_serves(self):
        repo = self.tree()
        self.installed()
        services = f"│ 1 │ hf:{NANO_REPO}@main │ {NANO_REPO} │ - │ Ready │"
        run = self.demo("uninstall", "--all", "--with-model", "--yes", script=repo / "demo.sh",
                        FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"), FAKE_ZRT_SERVICES=services)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"ZRT still serves {NANO_MODEL}", run.stdout)
        self.assertNotIn("zrt remove", self.zrt_calls())
        self.assertFalse((self.tmp / "home/.config/aware-care-demo").exists())

    def test_a_taken_device_port_names_the_port_options(self):
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FAKE_BUSY_PORTS="8180")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("Port 8180 is in use on this device (local uses API 8100, web 8180)", run.stderr)
        self.assertIn("./demo.sh local --instance my-demo --api-port 28100 --web-port 28180", run.stderr)
        self.assertNotIn("build_images.sh", run.stdout)
        run = self.demo("local", "--dry-run", "--instance", "my-demo", "--api-port", "28100", "--web-port", "28180",
                        FAKE_MODELS=served(NANO_MODEL), FAKE_BUSY_PORTS="8100 8180")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"--instance my-demo --data-root {self.tmp}/home/.local/share/my-demo --api-port 28100 "
                      "--web-port 28180", run.stdout)
        self.assertIn("-L 18180:127.0.0.1:28180", run.stdout)

    def test_it_refuses_to_run_as_root(self):
        fake_id = self.tmp / "bin/id"
        fake_id.write_text("#!/bin/sh\necho 0\n")
        fake_id.chmod(0o755)
        run = self.demo("uninstall", "--yes", **self.recording())
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("not with sudo or as root", run.stderr)
        self.assertEqual(self.changes(), "")
        self.assertEqual(self.demo("--help").returncode, 0)

    def test_options_are_checked(self):
        for args in (("mock", "--port", "70000"), ("local", "--web-port", "0"), ("local", "--api-port", "x"),
                     ("local", "--instance", "My Demo"), ("uninstall", "--with-model"), ("stop", "--all")):
            with self.subTest(args=args):
                run = self.demo(*args)
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)

    def test_a_failed_mock_start_stops_what_it_started(self):
        repo = self.tree()
        pids = self.tmp / "pids"
        run = self.demo("mock", script=repo / "demo.sh", FAKE_PIDS=str(pids), AWARECARE_DEMO_READY_SECONDS="2")
        started = [int(p) for p in pids.read_text().split()] if pids.exists() else []
        self.addCleanup(lambda: [os.kill(p, 9) for p in started if alive(p)])
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("so demo.sh stopped what it started", run.stderr)
        self.assertEqual(len(started), 2, run.stdout + run.stderr)
        deadline = time.time() + 5
        while any(alive(p) for p in started) and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse([p for p in started if alive(p)], "the API and web servers must be stopped")
        self.assertFalse((self.tmp / "logs/mock.state").exists())

    # ------------------------------------------------------------------ #533: readable output

    def sections(self, out: str) -> dict[str, list[str]]:
        """The output's sections: a heading (a line without indentation after a blank line) and its lines."""
        found: dict[str, list[str]] = {}
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if i >= 2 and line and not line.startswith(" ") and lines[i - 1] == "":
                body = []
                for after in lines[i + 1:]:
                    if not after:
                        break
                    body.append(after)
                found[line] = body
        return found

    def test_local_output_is_grouped_into_sections_with_blank_lines_between(self):
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stderr)
        lines = run.stdout.splitlines()
        self.assertEqual(lines[2], "", "a blank line after the header")
        self.assertEqual(list(self.sections(run.stdout)), ["Checks", "Model", "Build", "Deploy", "Telemetry", "Open it"])
        for heading in ("Checks", "Model", "Build", "Deploy", "Open it"):
            self.assertEqual(lines[lines.index(heading) - 1], "", f"no blank line before {heading}")
        self.assertIn("  ✓ Docker usable without sudo", self.sections(run.stdout)["Checks"])
        self.assertTrue(all(line.startswith("    $ ") for line in self.sections(run.stdout)["Build"]))

    def test_open_it_block_holds_the_tunnel_and_the_url(self):
        for args, tunnel, url in ((("local", "--dry-run"), "ssh -N -p 2222 -L 18180:127.0.0.1:8180 alice@192.0.2.3",
                                   "http://127.0.0.1:18180"),
                                  (("mock", "--dry-run", "--port", "15999"),
                                   "ssh -N -p 2222 -L 15999:127.0.0.1:15999 alice@192.0.2.3", "http://127.0.0.1:15999")):
            with self.subTest(args=args):
                run = self.demo(*args, FAKE_MODELS=served(NANO_MODEL))
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                block = "\n".join(self.sections(run.stdout)["Open it"])
                self.assertIn(tunnel, block)
                self.assertIn(f"Then open:  {url}", block)
                self.assertIn("localhost works too", block)  # #690
                self.assertEqual(list(self.sections(run.stdout))[-1], "Open it", "Open it comes last")

    def test_no_color_without_a_terminal_or_with_no_color(self):
        for env, args in (({}, ()), ({"NO_COLOR": "1"}, ()), ({"FORCE_COLOR": "1"}, ("--no-color",))):
            with self.subTest(env=env, args=args):
                for cmd in (("local", "--dry-run", *args), ("status", *args), ("--help", *args)):
                    run = self.demo(*cmd, FAKE_MODELS=served(NANO_MODEL), **env)
                    self.assertNotIn("\x1b", run.stdout + run.stderr, cmd)
        fails = self.demo("local", "--dry-run", FAKE_DOCKER="denied", FAKE_MODELS=served(NANO_MODEL))
        self.assertNotIn("\x1b", fails.stderr)

    def test_force_color_colors_the_same_layout(self):
        plain = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL))
        color = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FORCE_COLOR="1")
        self.assertIn("\x1b[", color.stdout)
        self.assertEqual(ANSI.sub("", color.stdout), plain.stdout)
        fails = self.demo("local", "--dry-run", FAKE_DOCKER="denied", FAKE_MODELS=served(NANO_MODEL), FORCE_COLOR="1")
        self.assertIn("\x1b[", fails.stderr)
        self.assertIn("      sudo usermod -aG docker alice\n", ANSI.sub("", fails.stderr))
        self.assertIn("\x1b[", self.demo("--help", FORCE_COLOR="1").stdout)

    def test_648_one_scheme_green_done_yellow_fix_red_error_with_the_command_to_run(self):
        """#648: ✓ green; ! yellow with a plain-words Fix: line; ✗ red with why and the one command that fixes it
        (Run:); detail lines dim; headings that stand out. The same text without color off a terminal."""
        green, yellow, red, dim, bold, under = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[2m", "\x1b[1m", "\x1b[4m"
        color = {"FORCE_COLOR": "1", "TERM": "xterm-256color"}
        run = self.demo("doctor", FAKE_LINGER="no", **self.machine("gb10"), **color)
        out = run.stdout
        self.assertRegex(out, re.escape(green) + r".*✓")
        self.assertRegex(out, re.escape(yellow) + r".*!.*Lingering is off")
        self.assertIn(f"{yellow}Fix:", out)
        self.assertIn(f"{dim}System memory: 119.6 GB", out)  # a detail
        self.assertRegex(out, re.escape(under) + r".*Machine")  # a heading
        plain = ANSI.sub("", out)
        self.assertIn("  ! Lingering is off: the model stops when you log out\n"
                      "    Fix: an administrator runs, once: sudo loginctl enable-linger alice", plain)
        # every error: what happened, why, then the command that fixes it
        cases = ((("local", "--dry-run"), {"FAKE_DOCKER": "denied"}, "An administrator must do 1 thing for alice",
                  "./demo.sh local"),
                 (("local", "--dry-run"), {"FAKE_NO_BUS": "1"}, "systemctl --user cannot reach your systemd session",
                  "ssh alice@localhost"),
                 (("local", "--dry-run"), {"FAKE_BUSY_PORTS": "8180"}, "Port 8180 is in use on this device",
                  "./demo.sh local --instance my-demo --api-port 28100 --web-port 28180"),
                 (("local", "--dry-run"), {"FAKE_DIRECT": "timeout"}, "ghcr.io does not answer (timeout)",
                  "export HTTP_PROXY=<proxy> HTTPS_PROXY=<proxy>"),
                 (("check-model",), {"FAKE_MODELS": served("other"), **self.machine("gb10")}, "ZRT does not serve",
                  "./demo.sh model"))
        for args, env, what, command in cases:
            with self.subTest(what=what):
                run = self.demo(*args, **{"FAKE_MODELS": served(NANO_MODEL), **env, **color})
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertRegex(run.stderr, re.escape(red) + ".*✗")
                err = ANSI.sub("", run.stderr).splitlines()
                first = next(i for i, line in enumerate(err) if line.startswith("  ✗ "))
                self.assertIn(what, err[first])
                self.assertTrue(err[first + 1].startswith("    ") and "Run:" not in err[first + 1], "why comes first")
                runs = [line for line in err if line.startswith("    Run: ")]
                self.assertTrue(any(command in line for line in runs), (command, err))
                self.assertIn(f"{bold}{command.split()[0]}", run.stderr.replace(red, ""))  # the command in bold
                plain = self.demo(*args, **{"FAKE_MODELS": served(NANO_MODEL), **env})
                self.assertNotIn("\x1b", plain.stdout + plain.stderr)
                self.assertEqual(ANSI.sub("", run.stderr).replace(str(self.tmp), ""),
                                 plain.stderr.replace(str(self.tmp), ""))

    def test_a_failure_prints_the_fix_then_the_log_path_and_its_last_lines(self):
        run = self.model_run(FAKE_ZRT_MODELS=zrt_models("hf:Qwen/Qwen3-32B@main"), FAKE_PULL_FAIL="1")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"→ Downloading {NANO_REPO}@{NANO_PINNED}", run.stdout)
        self.assertIn("✗ zrt pull failed", run.stderr)
        self.assertIn("    The last lines of its log, below, say why; fix that, then rerun:\n    Run: ./demo.sh model", run.stderr)
        log = re.search(r"Log: (\S+)", run.stderr)
        self.assertIsNotNone(log, run.stderr)
        self.assertTrue(Path(log.group(1)).is_file())
        self.assertIn("│ error: 403 Forbidden from huggingface.co", run.stderr)
        self.assertFalse((self.tmp / "systemctl.log").exists(), "nothing is installed after a failed download")


    # ------------------------------------------------------------------ #549: buildx on the manager's HP Z8 (conda)

    def conda_shell(self) -> dict[str, str]:
        """A conda "(base)" shell whose own docker comes first on PATH (the same stand-in), as on the manager's Z8."""
        conda = self.tmp / "miniconda3"
        (conda / "bin").mkdir(parents=True)
        shutil.copy(self.tmp / "bin/docker", conda / "bin/docker")
        return {"PATH": f"{conda / 'bin'}:{self.env['PATH']}", "CONDA_PREFIX": str(conda), "CONDA_DEFAULT_ENV": "base"}

    def test_549_the_managers_case_buildx_found_and_the_conda_docker_named(self):
        """On his Z8 `docker buildx version` failed in a conda (base) shell, and `docker docker-buildx --version` worked.
        That command prints Docker's own version, so it proves nothing; the plugin binary in a cli-plugins directory,
        run directly, is buildx. demo.sh finds it, names the conda Docker CLI and says how to get the system one."""
        plugins = self.plugin_dir()
        env = {**self.conda_shell(), "FAKE_BUILDX": "dir", "AWARECARE_DOCKER_PLUGIN_DIRS": str(plugins)}
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), **env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"✓ {plugins}/docker-buildx (the buildx plugin, run directly)", run.stdout)
        self.assertIn(f"! Docker CLI: {self.tmp}/miniconda3/bin/docker, from the conda environment base, comes before "
                      f"{self.tmp}/bin/docker on PATH", run.stdout)
        self.assertIn("Fix: conda deactivate", run.stdout)
        self.assertIn(f"PATH={self.tmp}/bin:$PATH ./demo.sh local", run.stdout)
        doctor = self.demo("doctor", FAKE_MODELS=served(NANO_MODEL), **env)
        self.assertIn("from the conda environment base", doctor.stdout)
        self.assertIn(f"✓ {plugins}/docker-buildx (the buildx plugin, run directly)", doctor.stdout)
        # Outside conda, doctor names the Docker CLI it uses.
        plain = self.demo("doctor", FAKE_MODELS=served(NANO_MODEL))
        self.assertIn(f"✓ Docker CLI: {self.tmp}/bin/docker", plain.stdout)
        self.assertNotIn("conda", plain.stdout)
        # His exact command, when it does answer as buildx, is used as it is.
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FAKE_BUILDX="docker-cmd")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("✓ docker docker-buildx", run.stdout)
        # The plugin directory in the user's home is one of the places looked at by default.
        home_plugins = self.plugin_dir("home/.docker/cli-plugins")
        env = {k: v for k, v in self.env.items() if k != "AWARECARE_DOCKER_PLUGIN_DIRS"}
        run = subprocess.run(["bash", str(SCRIPT), "local", "--dry-run"], capture_output=True, text=True, timeout=60,
                             env={**env, "FAKE_BUILDX": "dir", "FAKE_MODELS": served(NANO_MODEL)}, stdin=subprocess.DEVNULL)
        self.assertIn(f"✓ {home_plugins}/docker-buildx (the buildx plugin, run directly)", run.stdout)

    # ------------------------------------------------------------------ #549: ZRT on any loopback port

    def test_549_the_proxy_port_comes_from_zrt_config_everywhere(self):
        """ZRT's proxy on 9093 (zrt config get proxy.port; nothing answers on 8080): local, the deploy, status, doctor,
        check-model and setup all use it without an option."""
        port = {"FAKE_ZRT_PORT": "9093", "FAKE_PROXY_PORT": "9093", "FAKE_MODELS": served(NANO_MODEL)}
        url = "http://127.0.0.1:9093/v1"
        run = self.demo("local", "--dry-run", **port)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"✓ ZRT serves {NANO_MODEL} on {url}", run.stdout)
        self.assertIn(f"--zrt-base-url {url} ", run.stdout)
        self.assertNotIn("8080", run.stdout)
        self.assertIn(f"ZRT serves {NANO_MODEL} on {url}", self.demo("status", **port).stdout)
        doctor = self.demo("doctor", "--device", "nano", **port).stdout
        self.assertIn(f"✓ ZRT address: {url} (from zrt config get proxy.port)", doctor)
        self.assertIn(f"✓ ZRT serves it: {NANO_MODEL} on {url}", doctor)
        self.assertIn(f"AI_REGRESSION_ZRT_URL={url}", self.demo("check-model", "--dry-run", **port).stdout)
        setup = self.demo("setup", "--dry-run", "--device", "nano", **port)
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        self.assertIn(f"ZRT already serves {NANO_MODEL} on {url}; nothing to do", setup.stdout)
        self.assertIn(f"--zrt-base-url {url} ", setup.stdout)
        # ZRT's mode decides which configuration answers
        self.demo("doctor", "--zrt-mode", "user", **port)
        self.assertIn("zrt -m user config get proxy.port", self.zrt_calls())

    def test_549_model_on_another_port_writes_it_for_the_serve_script_which_also_reads_zrt_config(self):
        url = "http://127.0.0.1:9093/v1"
        run = self.model_run(FAKE_ZRT_PORT="9093", FAKE_PROXY_PORT="9093", FAKE_MODELS_AFTER=served(NANO_MODEL),
                             FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"ZRT serves {NANO_MODEL} on {url}", run.stdout)
        env = (self.tmp / "home/.config/aware-care-demo/model.env").read_text()
        self.assertIn(f"AWARECARE_ZRT_URL={url}\n", env)
        # The unit's serve script, without model.env's address, asks ZRT for its proxy port too.
        script = self.tmp / "home/.local/share/aware-care-demo/zrt/serve-model.sh"
        for name in ("nano", "fury", "generic"):
            with self.subTest(script=name):
                path = ROOT / f"infra/{name}/zrt/serve-model.sh"
                base = {**self.env, "AWARECARE_MODEL_URI": f"hf:{NANO_REPO}@main", "AWARECARE_MODEL_LABEL": NANO_MODEL,
                        "FAKE_PROXY_PORT": "9093", "FAKE_MODELS": served(NANO_MODEL, FURY_MODEL)}
                out = subprocess.run(["bash", str(path)], env={**base, "FAKE_ZRT_PORT": "9093"}, capture_output=True,
                                     text=True, timeout=30)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertIn("is already served", out.stdout)
                out = subprocess.run(["bash", str(path)], env={**base, "FAKE_ZRT_PORT": "8080"}, capture_output=True,
                                     text=True, timeout=30)
                self.assertIn("zrt-stand-in s", out.stdout)  # not served on 8080: it starts the model
        self.assertTrue(script.exists())

    def test_549_zrt_port_option_and_a_port_zrt_is_not_set_to(self):
        port = {"FAKE_PROXY_PORT": "9093", "FAKE_MODELS": served(NANO_MODEL)}  # zrt config says 8080
        run = self.demo("local", "--dry-run", "--zrt-port", "9093", **port)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("--zrt-base-url http://127.0.0.1:9093/v1 ", run.stdout)
        self.assertIn("✓ ZRT address: http://127.0.0.1:9093/v1 (from --zrt-port)", self.demo("doctor", "--zrt-port", "9093", **port).stdout)
        # ZRT serves through its proxy's port: asked for another one, model says how to set ZRT's, and changes nothing
        run = self.demo("model", "--device", "nano", "--zrt-port", "9094", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"),
                        **self.recording())
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("✗ ZRT's proxy is set to port 8080 (zrt config get proxy.port), so ZRT would serve", run.stderr)
        self.assertIn("./demo.sh model --zrt-port 8080", run.stderr)
        self.assertIn("zrt -m system config set proxy.port 9094", run.stderr)
        self.assertEqual(self.changes(), "")
        for bad in (("--zrt-port", "0"), ("--zrt-port", "http"), ("--zrt-port", "70000"),
                    ("--zrt-port", "9093", "--zrt-url", "http://127.0.0.1:9093/v1")):
            with self.subTest(args=bad):
                self.assertEqual(self.demo("local", "--dry-run", *bad).returncode, 2)

    def test_549_a_service_endpoint_is_found_beside_a_proxy_on_any_port(self):
        endpoint = self.zrt_service(NANO_REPO)
        run = self.demo("local", "--dry-run", FAKE_ZRT_PORT="9093", FAKE_PROXY_PORT="9093",
                        FAKE_MODELS=served("Prash_0.30.0"), FAKE_ZRT_SERVICES=self.z8_services(endpoint),
                        **self.machine("z8"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"! ZRT's proxy on 9093 does not list the model; using the service endpoint {endpoint}/v1", run.stdout)
        self.assertIn(f"--zrt-base-url {endpoint}/v1 ", run.stdout)
        # doctor shows ZRT's own address in its ZRT section, and where it found the model in its Model section
        doctor = self.demo("doctor", FAKE_ZRT_PORT="9093", FAKE_PROXY_PORT="9093", FAKE_MODELS=served("Prash_0.30.0"),
                           FAKE_ZRT_SERVICES=self.z8_services(endpoint), **self.machine("z8")).stdout
        self.assertIn("✓ ZRT address: http://127.0.0.1:9093/v1 (from zrt config get proxy.port)", doctor)
        self.assertIn("✓ ZRT on http://127.0.0.1:9093/v1 serves: Prash_0.30.0", doctor)
        self.assertIn(f"✓ ZRT serves it: {NANO_MODEL} as {NANO_REPO} on {endpoint}/v1", doctor)
        # --zrt-port names an address: no discovery
        run = self.demo("local", "--dry-run", "--zrt-port", "9093", FAKE_PROXY_PORT="9093",
                        FAKE_MODELS=served("Prash_0.30.0"), FAKE_ZRT_SERVICES=self.z8_services(endpoint),
                        **self.machine("z8"))
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)

    # ------------------------------------------------------------------ #549: ./demo.sh setup

    FAKE_DEPLOY = """\
#!/usr/bin/env python3
# Stand-in for infra/deploy/nano_deploy.py (#549 setup tests): deploy records state/current.json, status reports it.
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
opt = lambda name, default=None: args[args.index(name) + 1] if name in args else default
root = Path(opt("--data-root", os.path.expanduser("~/.local/share/aware-care-demo")))
state = root / "state" / "current.json"
with open(os.environ["FAKE_DEPLOY_LOG"], "a") as log:
    log.write(" ".join(a for a in args if a in ("presenter-key", "deploy", "status", "power-sampler", "--remove",
                                                "--dry-run")) + "\\n")
line = f"* * * * * /usr/bin/flock -n {root}/telemetry/sampler.lock /usr/bin/python3 {root}/telemetry/power_sampler.py"
if "power-sampler" in args:  # #678: FAKE_SAMPLER=kept (its line is there), failed (crontab unusable), else added
    how = os.environ.get("FAKE_SAMPLER", "added")
    if "--dry-run" in args:
        print(json.dumps({"cron_keeper": how == "kept", "would": "nothing" if how == "kept" else "add", "line": line}))
    elif how == "failed":
        print(json.dumps({"error": "crontab - failed: You are not allowed to use this program"}))
        sys.exit(1)
    else:
        print(json.dumps({"installed": f"{root}/telemetry/power_sampler.py", "cron_keeper": True,
                          "added": how != "kept", "line": line}))
elif "deploy" in args:
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"mode": opt("--mode"), "model_id": opt("--model-id"), "app_commit": opt("--app-commit"),
                                 "release_tag": opt("--release-tag"), "api_image": opt("--api-image"),
                                 "zrt": opt("--zrt-base-url")}, indent=2))
    print("[nano-deploy] outcome: SUCCEEDED")
elif "status" in args:
    cur = json.loads(state.read_text()) if state.exists() else None
    up = {"running": True, "status": "running"} if cur else None
    print(json.dumps({"current": cur, "containers": {"api": up, "web": up}, "data_root": str(root),
                      "readiness": {"readiness": "ready" if cur else None}, "model_base_url": (cur or {}).get("zrt")}))
"""

    def setup_clone(self) -> Path:
        """A committed copy of what setup reads, whose deploy tool and image build are stand-ins (a real run builds and
        deploys nothing): setup's own steps run for real against the stand-ins on PATH."""
        repo = self.tmp / "clone"
        for rel in ("demo.sh", "apps/web/package-lock.json"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, repo / rel)
        shutil.copytree(ROOT / "infra", repo / "infra", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "apps/api/app/runtime", repo / "apps/api/app/runtime",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (repo / "infra/deploy/nano_deploy.py").write_text(self.FAKE_DEPLOY)
        (repo / "infra/deploy/build_images.sh").write_text('#!/bin/sh\necho "build_images.sh $*" >> "$FAKE_BUILD_LOG"\n')
        (repo / "infra/deploy/build_images.sh").chmod(0o755)
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        for cmd in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-qm", "setup test"]):
            subprocess.run([*git, *cmd], check=True, capture_output=True)
        self.env.update(FAKE_DEPLOY_LOG=str(self.tmp / "deploy.log"), FAKE_BUILD_LOG=str(self.tmp / "build.log"),
                        FAKE_STARTED=str(self.tmp / "started"), FAKE_SYSTEMCTL_LOG=str(self.tmp / "systemctl.log"))
        return repo

    def log(self, name: str) -> str:
        path = self.tmp / name
        return path.read_text() if path.exists() else ""

    def test_549_setup_on_a_fresh_machine_serves_the_model_then_builds_and_deploys(self):
        repo = self.setup_clone()
        z8 = {**self.machine("z8"), "FAKE_MODELS_AFTER": served(NANO_MODEL)}
        run = self.demo("setup", script=repo / "demo.sh", **z8)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = run.stdout
        self.assertEqual(out.splitlines()[0], "Aware Care · setup on HP Z8 Fury G5 Workstation Desktop PC")
        # in order: the doctor checks, the model (download, its size first; unit; wait), the build, the deploy, Open it
        order = ["\nMachine\n", "\nDocker and network\n", "\nZRT\n", "\nModel\n", "\nPorts\n", "\nServe the model\n",
                 "Download: Qwen/Qwen3.6-35B-A3B-FP8@95a723d08a9490559dae23d0cff1d9466213d989, about 37.49 GB",
                 "\nInstall\n", "\nStart\n", f"✓ ZRT serves {NANO_MODEL} on http://127.0.0.1:8080/v1",
                 "\nBuild\n", "\nDeploy\n", "outcome: SUCCEEDED", "\nOpen it\n", "http://127.0.0.1:18180"]
        positions = [out.index(step) for step in order]
        self.assertEqual(positions, sorted(positions), out)
        self.assertIn(f"pull hf:{NANO_REPO}@{NANO_PINNED}", self.zrt_calls())
        self.assertIn("--gpu-devices=0,1", (self.tmp / "home/.local/share/aware-care-demo/zrt/serve.args").read_text())
        self.assertIn("build_images.sh --platform linux/amd64", self.log("build.log"))
        self.assertEqual(self.log("deploy.log").split(), ["status", "presenter-key", "deploy", "power-sampler"])
        # #549: the API reads a candidate manifest, not the Nano's qualification
        manifest = json.loads((self.tmp / "home/.local/share/aware-care-demo/device/model-manifest.json").read_text())
        self.assertEqual(manifest["status"], "candidate")

        # A rerun skips everything: the model is served, the app runs this commit and answers ready.
        for name in ("build.log", "deploy.log", "zrt.log", "systemctl.log"):
            (self.tmp / name).unlink(missing_ok=True)
        # #640: the first run turned the model's watchdog on
        again = self.demo("setup", script=repo / "demo.sh", FAKE_RUNNING_IMAGE="aware-care-demo-api:local",
                          FAKE_WD_TIMER="on", **z8)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn(f"✓ ZRT already serves {NANO_MODEL} on http://127.0.0.1:8080/v1; nothing to do", again.stdout)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        self.assertIn(f"✓ The app already runs commit {head[:12]} with {NANO_MODEL} on http://127.0.0.1:8080/v1 and "
                      "answers ready; nothing to build or deploy (--rebuild builds and deploys again)", again.stdout)
        self.assertIn("\nOpen it\n", again.stdout)
        self.assertEqual(self.log("build.log"), "")
        # #678: the power sampler's step runs again; its line is already there, so it changes nothing
        self.assertEqual(self.log("deploy.log").split(), ["status", "power-sampler"])
        self.assertEqual(self.log("systemctl.log"), "")
        self.assertNotRegex(self.zrt_calls(), r"zrt -m \w+ (pull|service start)")

        # --rebuild builds and deploys again (the model stays as it is)
        rebuild = self.demo("setup", "--rebuild", script=repo / "demo.sh", FAKE_RUNNING_IMAGE="aware-care-demo-api:local",
                            FAKE_WD_TIMER="on", **z8)
        self.assertEqual(rebuild.returncode, 0, rebuild.stdout + rebuild.stderr)
        self.assertIn("build_images.sh", self.log("build.log"))
        self.assertIn("deploy", self.log("deploy.log").split())
        self.assertEqual(self.log("systemctl.log"), "")

    def test_549_setup_stops_at_the_first_failed_check_with_its_fix(self):
        repo = self.setup_clone()
        run = self.demo("setup", script=repo / "demo.sh", FAKE_DOCKER="denied", **self.machine("z8"), **self.recording())
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        # #694: the administrator block, before any check that downloads
        self.assertIn("✗ An administrator must do 1 thing for alice, once, before setup can go on", run.stderr)
        self.assertIn("Copy this block to an administrator:\n      sudo usermod -aG docker alice\n", run.stderr)
        self.assertNotIn("Serve the model", run.stdout)
        self.assertEqual(self.changes() + self.log("build.log") + self.log("deploy.log"), "")
        self.assertNotIn("pull", self.zrt_calls())
        # too little disk for the model's download: stops before it downloads
        run = self.demo("setup", script=repo / "demo.sh", FAKE_FREE_GB="13", **self.machine("z8"))
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("✗ Disk: 13 GB free for ZRT's models", run.stderr)
        self.assertNotIn("pull", self.zrt_calls())
        # no model for this machine: it says so and offers mock mode
        run = self.demo("setup", script=repo / "demo.sh", **self.machine("8gb"))
        self.assertEqual(run.returncode, 1)
        self.assertIn("✗ No local model: 8 GB of GPU memory is less than the smallest model needs (12 GB)", run.stderr)
        self.assertIn("./demo.sh setup --mock", run.stderr)

    def test_549_setup_dry_run_changes_nothing(self):
        repo = self.setup_clone()
        run = self.demo("setup", "--dry-run", script=repo / "demo.sh", **self.machine("z8"), **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = run.stdout
        self.assertEqual(out.splitlines()[0], "Aware Care · setup on HP Z8 Fury G5 Workstation Desktop PC · dry run")
        for line in (f"pull hf:{NANO_REPO}@{NANO_PINNED}", "install -D -m 644 infra/generic/zrt/aware-care-zrt-model.service",
                     "Dry run: nothing was downloaded, installed or started.", "infra/deploy/build_images.sh --platform linux/amd64",
                     "deploy --mode local --model-id qwen3.6-35b-a3b-fp8", "Dry run: these commands were printed, not run.",
                     "ssh -N -p 2222 -L 18180:127.0.0.1:8180 alice@192.0.2.3"):
            self.assertIn(line, out)
        self.assertEqual(self.changes() + self.log("build.log"), "")
        self.assertEqual(self.log("deploy.log").split(), ["status", "power-sampler", "--dry-run"])  # read-only
        self.assertFalse((self.tmp / "home").exists(), "a dry run installs nothing")
        # ./demo.sh alone with --dry-run is setup (without a terminal and options, it prints the help)
        self.assertIn("· setup on HP Z8", self.demo("--dry-run", script=repo / "demo.sh", **self.machine("z8")).stdout)
        alone = self.demo(script=repo / "demo.sh")
        self.assertEqual(alone.returncode, 2)
        self.assertIn("./demo.sh setup", alone.stdout)

    def test_549_setup_mock_runs_mock_mode_without_docker_or_a_model(self):
        run = self.demo("setup", "--mock", "--dry-run", FAKE_DOCKER="denied", **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stdout.splitlines()[0], "Aware Care · mock mode (no model, scripted synthetic results) · dry run")
        self.assertIn("uv run uvicorn app.main:app", run.stdout)
        self.assertNotIn("Docker", run.stdout)
        self.assertEqual(self.changes(), "")
        self.assertEqual(self.zrt_calls(), "")
        # already running and ready on the same ports: nothing to do
        import http.server
        import threading

        class Ready(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"readiness":"ready"}')

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Ready)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        state = self.tmp / "logs/mock.state"
        state.parent.mkdir(parents=True, exist_ok=True)
        web = server.server_address[1]
        state.write_text(f"API_PID={proc.pid}\nWEB_PID={proc.pid}\nAPI_PORT=8000\nWEB_PORT={web}\nBROWSER_PORT=15173\n")
        self.env["FAKE_REAL_CURL"] = shutil.which("curl")  # the readiness answer comes from the server above
        run = self.demo("setup", "--mock", **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Mock mode already runs (API 127.0.0.1:8000", run.stdout)
        self.assertIn("nothing to do", run.stdout)
        self.assertIn("http://127.0.0.1:15173", run.stdout)
        self.assertEqual(self.changes(), "")
        self.assertIsNone(proc.poll(), "it did not restart the servers")
        self.assertEqual(self.demo("local", "--mock").returncode, 2)  # --mock goes with setup

    # ------------------------------------------------------------------ #537: any NVIDIA machine

    MACHINES = {  # nvidia-smi rows, MemTotal kB, DMI product name, uname -m
        "z8": ("0, NVIDIA RTX PRO 5000 72GB Blackwell, 73728, 12.0, 580.95.05\n"
               "1, NVIDIA RTX PRO 5000 72GB Blackwell, 73728, 12.0, 580.95.05", 263000000,
               "HP Z8 Fury G5 Workstation Desktop PC", "x86_64"),
        "24gb": ("0, NVIDIA GeForce RTX 4090, 24564, 8.9, 580.95.05", 65000000, "HP Z4 G5 Workstation", "x86_64"),
        "8gb": ("0, NVIDIA GeForce RTX 4060, 8188, 8.9, 580.95.05", 16000000, "HP Z2 Tower G9 Workstation", "x86_64"),
        "gb10": ("0, NVIDIA GB10, [N/A], 12.1, 580.95.05", 125442420, "HP ZGX Nano G1n AI Station", "aarch64"),
        "gb300": ("0, NVIDIA GB300, 256703, 10.3, 595.99.02", 779000000, "HP ZGX Fury G1n AI Station", "aarch64"),
    }

    def machine(self, name: str) -> dict[str, str]:
        """The environment in which demo.sh's hardware helper sees the named machine."""
        rows, mem_kb, product, arch = self.MACHINES[name]
        root = self.tmp / f"machine-{name}"
        (root / "proc").mkdir(parents=True, exist_ok=True)
        (root / "proc/meminfo").write_text(f"MemTotal:       {mem_kb} kB\n")
        (root / "sys/class/dmi/id").mkdir(parents=True, exist_ok=True)
        (root / "sys/class/dmi/id/product_name").write_text(product + "\n")
        (root / "arch").write_text(arch + "\n")
        return {"AWARECARE_HW_ROOT": str(root), "FAKE_SMI_CSV": rows}

    def dollar_lines(self, out: str) -> list[str]:
        return [line.strip()[2:] for line in out.splitlines() if line.strip().startswith("$ ")]

    def test_doctor_names_the_machine_and_the_model_it_will_use(self):
        run = self.demo("doctor", FAKE_MODELS=served("Prash_0.30.0"), **self.machine("z8"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = run.stdout
        self.assertIn("✓ Machine: HP Z8 Fury G5 Workstation Desktop PC (x86_64; images for linux/amd64)", out)
        self.assertIn("✓ GPU: 2x NVIDIA RTX PRO 5000 72GB Blackwell, 72.0 GB each; 144 GB usable (the sum over the GPUs)",
                      out)
        self.assertIn("✓ Model for this machine: qwen3.6-35b-a3b-fp8 (Qwen/Qwen3.6-35B-A3B-FP8@95a723d, 37.49 GB)", out)
        self.assertIn("Candidate on this hardware", out)
        self.assertIn("qualified: HP ZGX Nano, 2026-10-15", out)
        self.assertIn("Serving: tensor parallel 2 (GPUs 0,1), gpu-memory-fraction 0.85, max-model-len 16384, max-num-seqs 1",
                      out)
        self.assertIn("Not downloaded yet: ./demo.sh setup (or model) downloads 37.49 GB", out)
        self.assertIn("✓ ZRT address: http://127.0.0.1:8080/v1 (from zrt config get proxy.port)", out)
        self.assertIn("mode system (from zrt config get mode)", out)
        for heading in ("Machine", "Docker and network", "ZRT", "Model", "Ports", "Verdict"):
            self.assertIn(f"\n{heading}\n", out)
        self.assertRegex(out, r"Verdict\n  (✓ Ready|✗ Fix \d+ items? first)")
        run = self.demo("doctor", **self.machine("24gb"))
        self.assertIn("✓ Model for this machine: qwen3-14b-fp8 (Qwen/Qwen3-14B-FP8@9a283b4, 16.34 GB)", run.stdout)
        self.assertIn("24 to 63 GB", run.stdout)
        run = self.demo("doctor", **self.machine("gb10"))
        self.assertIn("✓ Qualified on this hardware (HP ZGX Nano, 2026-10-15)", run.stdout)
        self.assertIn("MTP speculative decoding", run.stdout)
        run = self.demo("doctor", **self.machine("8gb"))
        self.assertEqual(run.returncode, 0)
        self.assertIn("✗ No local model: 8 GB of GPU memory is less than the smallest model needs (12 GB)", run.stdout)
        self.assertRegex(run.stdout, r"✗ Fix \d+ items? first")
        self.assertIn("./demo.sh mock", run.stdout)

    def test_model_dry_run_on_the_z8_serves_qwen36_with_tensor_parallel_2(self):
        run = self.demo("model", "--dry-run", FAKE_ZRT_MODELS=zrt_models("hf:Qwen/Qwen3-32B@main"), **self.machine("z8"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = run.stdout
        self.assertEqual(out.splitlines()[0],
                         "Aware Care · serve the model with ZRT on HP Z8 Fury G5 Workstation Desktop PC · dry run")
        self.assertIn(f"-m system pull hf:{NANO_REPO}@{NANO_PINNED}", out)
        self.assertIn(f"Download: {NANO_REPO}@{NANO_PINNED}, about 37.49 GB", out)
        self.assertIn("install -D -m 755 infra/generic/zrt/serve-model.sh", out)
        self.assertIn("install -D -m 644 infra/generic/zrt/aware-care-zrt-model.service", out)
        self.assertIn(f"AWARECARE_MODEL_URI=hf:{NANO_REPO}@{NANO_PINNED} AWARECARE_MODEL_LABEL={NANO_MODEL}", out)
        # #549: ZRT's --gpu-devices sets the tensor parallel size itself
        self.assertIn("--gpu-devices=0,1", out)
        self.assertNotIn("tensor-parallel-size", out)
        self.assertIn("--gpu-memory-fraction=0.85", out)
        self.assertNotIn("speculative", out)
        self.assertFalse((self.tmp / "home").exists(), "a dry run installs nothing")

    def test_local_dry_run_on_the_z8_builds_for_amd64_and_deploys_the_generic_profile(self):
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(f"{NANO_REPO}@main"), **self.machine("z8"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = run.stdout
        self.assertIn("Model: qwen3.6-35b-a3b-fp8, a candidate on this hardware", out)
        build, files, key, deploy, sampler = self.dollar_lines(out)
        self.assertTrue(sampler.endswith(" power-sampler"), sampler)  # #678
        self.assertTrue(build.startswith("infra/deploy/build_images.sh --platform linux/amd64 "), build)
        self.assertIn("hardware.py device-files --model qwen3.6-35b-a3b-fp8 --out", files)
        for line in (key, deploy):
            self.assertIn("--config infra/deploy/demo-generic.json", line)
            self.assertIn("--device-name HP\\ Z8\\ Fury\\ G5\\ Workstation\\ Desktop\\ PC "
                          "--device-short-name Z8\\ Fury\\ G5", line)
            self.assertIn("/device", line)
        self.assertIn(f"deploy --mode local --model-id {NANO_MODEL} ", deploy)
        self.assertIn("--expected-arch amd64", deploy)

    def test_a_24_gb_card_gets_the_14b_candidate(self):
        model = self.demo("model", "--dry-run", **self.machine("24gb"))
        self.assertEqual(model.returncode, 0, model.stdout + model.stderr)
        self.assertIn("pull hf:Qwen/Qwen3-14B-FP8@9a283b4a5efbc09ce247e0ae5b02b744739e525a", model.stdout)
        self.assertNotIn("tensor-parallel", model.stdout)
        local = self.demo("local", "--dry-run", FAKE_MODELS=served("qwen3-14b-fp8"), **self.machine("24gb"))
        self.assertEqual(local.returncode, 0, local.stdout + local.stderr)
        self.assertIn("ZRT serves qwen3-14b-fp8", local.stdout)
        self.assertIn("--device-name HP\\ Z4\\ G5\\ Workstation", local.stdout)
        self.assertIn("deploy --mode local --model-id qwen3-14b-fp8", local.stdout)
        small = self.demo("local", "--dry-run", **self.machine("8gb"))
        self.assertEqual(small.returncode, 1)
        self.assertIn("less than the smallest model needs (12 GB)", small.stderr)
        self.assertIn("./demo.sh mock", small.stderr)

    def test_model_option_picks_a_catalogue_entry(self):
        run = self.demo("model", "--dry-run", "--model", "qwen3-8b-fp8", **self.machine("z8"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("pull hf:Qwen/Qwen3-8B-FP8@220b46e3b2180893580a4454f21f22d3ebb187d3", run.stdout)
        bad = self.demo("model", "--dry-run", "--model", "llama-3", **self.machine("z8"))
        self.assertEqual(bad.returncode, 1)
        self.assertIn("not in the catalogue", bad.stderr)

    def test_zrt_mode_user_is_passed_to_every_zrt_call(self):
        run = self.demo("model", "--zrt-mode", "user", FAKE_STARTED=str(self.tmp / "started"),
                        FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"), FAKE_MODELS_AFTER=served(f"{NANO_REPO}@main"),
                        **self.machine("z8"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        calls = [c for c in self.zrt_calls().splitlines() if c.strip()]
        self.assertTrue(calls)
        self.assertTrue(all(c.startswith("zrt -m user ") for c in calls), calls)
        env = (self.tmp / "home/.config/aware-care-demo/model.env").read_text()
        self.assertIn("AWARECARE_ZRT_MODE=user\n", env)
        script = self.tmp / "home/.local/share/aware-care-demo/zrt/serve-model.sh"
        values = dict(line.split("=", 1) for line in env.splitlines())
        out = subprocess.run(["bash", str(script)], env={**self.env, **values}, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"zrt-stand-in service start hf:{NANO_REPO}@main --label {NANO_MODEL} --gpu-memory-fraction=0.85",
                      out.stdout)
        self.assertIn("--gpu-devices=0,1", out.stdout)
        self.assertIn("zrt -m user service start", self.zrt_calls())
        # the mode from zrt's own configuration, when no option names it
        self.demo("model", "--dry-run", FAKE_ZRT_MODE="user", **self.machine("24gb"))
        self.assertIn("zrt -m user models", self.zrt_calls())
        self.assertEqual(self.demo("model", "--zrt-mode", "root").returncode, 2)

    def test_the_zgx_dry_runs_are_unchanged(self):
        """Golden output: the Nano's and the Fury's `model` and `local` dry runs are those from before #537, except that
        zrt calls name ZRT's mode (-m system) and, since #540, `local` checks its device ports ("Ports free") and names
        the home page's buttons, since #640 `model` installs and turns on the model's watchdog, since #644 `local` and
        `model` check the login session first, since #678 `local` keeps the GPU power sampler running (Telemetry), since #694
        `model` checks every administrator step in one line, since #697 it says how long the model start takes (also in
        a dry run), and since #690 the Open it box says localhost works too."""
        golden = json.loads((ROOT / "tests/tooling/golden/demo-zgx-dry-runs.json").read_text())
        for name, case in golden.items():
            with self.subTest(case=name):
                run = self.demo(*case["args"], **case["env"])
                self.assertEqual((run.returncode, normalised(run.stdout, self.tmp, ROOT)),
                                 (case["returncode"], case["stdout"]))

    def test_check_model_runs_the_regression_set_here_and_writes_a_report(self):
        uv_log = self.tmp / "uv.log"
        run = self.demo("check-model", FAKE_MODELS=served("qwen3-14b-fp8"), FAKE_UV_LOG=str(uv_log),
                        **self.machine("24gb"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ZRT serves qwen3-14b-fp8 on http://127.0.0.1:8080/v1", run.stdout)
        self.assertIn("| here | 63 | 20/20 | 0 | 25/25 | 10/10 | 0 | PASS |", run.stdout)
        self.assertIn("Result: PASS", run.stdout)
        self.assertIn("AWARECARE_MODEL_ID=qwen3-14b-fp8 AWARECARE_MODEL_BASE_URL=http://127.0.0.1:8080/v1",
                      uv_log.read_text())
        path = Path(re.search(r"Report: (\S+\.json)", run.stdout).group(1))
        report = json.loads(path.read_text())
        self.assertEqual(report["model"]["label"], "qwen3-14b-fp8")
        self.assertEqual(report["model"]["status_on_this_hardware"], "candidate")
        self.assertEqual(report["machine"]["device_name"], "HP Z4 G5 Workstation")
        self.assertEqual(report["result"]["summary"]["gate"], "PASS")
        # advisory: a failing gate still exits 0; a run that produced no report is an error
        failing = PASSING_REPORT.replace('"gate": "PASS", "gate_failures": []', '"gate": "FAIL", "gate_failures": ["RF02"]')
        run = self.demo("check-model", FAKE_MODELS=served("qwen3-14b-fp8"), FAKE_REPORT=failing, **self.machine("24gb"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("! Result: FAIL (advisory only; the model still runs)", run.stdout)
        run = self.demo("check-model", FAKE_MODELS=served("qwen3-14b-fp8"), FAKE_NO_REPORT="1", **self.machine("24gb"))
        self.assertEqual(run.returncode, 1)
        self.assertIn("The check did not run", run.stderr)
        run = self.demo("check-model", FAKE_MODELS=served("Prash_0.30.0"), **self.machine("24gb"))
        self.assertEqual(run.returncode, 1)
        self.assertIn("Serve it first:\n    Run: ./demo.sh model", run.stderr)

    # ------------------------------------------------------------------ #556 QA bug hunt (demo.sh)

    def test_556_uninstall_of_an_instance_keeps_a_folder_demo_sh_did_not_create(self):
        """#557: --instance zrt (or uv, keyrings, ...) names another program's ~/.local/share folder: never removed."""
        repo = self.tree()
        foreign = self.tmp / "home/.local/share/zrt/models/some-model"
        foreign.mkdir(parents=True)
        own = self.installed("scratch")[0].parent.parent  # ~/.local/share/scratch with state/current.json
        for args in (("--dry-run",), ("--yes",)):
            with self.subTest(args=args):
                run = self.demo("uninstall", "--instance", "zrt", *args, script=repo / "demo.sh", **self.recording())
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertNotIn("rm -rf", run.stdout)
                self.assertIn("not an Aware Care deployment", run.stdout)
                self.assertTrue(foreign.exists())
        run = self.demo("uninstall", "--instance", "scratch", "--yes", script=repo / "demo.sh", **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(own.exists(), "an instance's own data root is still removed")

    def test_589_uninstall_refuses_every_spelling_of_home_the_checkout_or_their_parents(self):
        """#589: $HOME//, $HOME/../home, /sub/../, a symlink or a trailing slash name the same protected folder."""
        repo = self.tree()
        home = self.tmp / "home"
        self.assertNotEqual(str(home.resolve()), str(Path.home().resolve()), "never the real home")
        (home / "state").mkdir(parents=True)  # the marker own_data_root accepts
        keep = home / "keep-unrelated.txt"
        keep.write_text("keep\n")
        (repo / "state").mkdir()
        (self.tmp / "home-link").symlink_to(home)
        (self.tmp / "repo-link").symlink_to(repo)
        aliases = [f"{home}//", f"{home}/../home", f"{home}/sub/../", f"{home}/.", f"{home}/", f"{self.tmp}/home-link",
                   f"{self.tmp}/home-link/", f"{self.tmp}/home-link/sub/..", f"{repo}/", f"{repo}//.",
                   f"{self.tmp}/repo-link/", f"{home}/..", f"{self.tmp}/", "//", "/tmp/.."]
        for alias in aliases:
            for args in (("--yes",), ("--all", "--yes"), ("--dry-run",)):
                with self.subTest(alias=alias, args=args):
                    run = self.demo("uninstall", *args, script=repo / "demo.sh", AWARECARE_DEMO_DATA_ROOT=alias,
                                    **self.recording())
                    self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                    self.assertIn("Refusing to delete the data root", run.stderr)
                    self.assertNotIn("Removed", run.stdout)
                    for path in (keep, home / "state", repo / "demo.sh", repo / "state"):
                        self.assertTrue(path.exists(), path)
        # the logs folder (--all) is checked the same way: kept, with the reason
        self.installed()
        run = self.demo("uninstall", "--all", "--yes", script=repo / "demo.sh",
                        AWARECARE_DEMO_LOG_DIR=f"{self.tmp}/home-link/", **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("is /, $HOME, the checkout or a folder that holds one of them", run.stdout)
        self.assertTrue(keep.exists())
        self.assertFalse((home / ".local/share/aware-care-demo").exists(), "the real data root is still removed")

    def test_589_uninstall_removes_its_own_data_root_however_it_is_spelt(self):
        """#589: the passing control: an alias of a data root demo.sh created is still removed, nothing else."""
        repo = self.tree()
        home = self.tmp / "home"
        keep = home / "keep-unrelated.txt"
        for alias in (f"{home}/.local/share/scratch/", f"{home}//.local/share/x/../scratch", "link/"):
            with self.subTest(alias=alias):
                own = self.installed("scratch")[0].parent.parent
                keep.write_text("keep\n")
                if alias == "link/":
                    link = self.tmp / "scratch-link"
                    link.unlink(missing_ok=True)
                    link.symlink_to(own)
                    alias = f"{link}/"
                run = self.demo("uninstall", "--instance", "scratch", "--yes", script=repo / "demo.sh",
                                AWARECARE_DEMO_DATA_ROOT=alias, **self.recording())
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn(f"Removed {own.resolve()} (the app's data", run.stdout)
                self.assertFalse(own.exists())
                self.assertTrue(keep.exists())

    def test_556_uninstall_of_another_instance_leaves_mock_mode_alone(self):
        """#564: only the default instance's uninstall stops mock mode and removes its data."""
        repo = self.tree()
        (repo / "runtime-data/api").mkdir(parents=True)
        (repo / "runtime-data/presenter-dev.key").write_text("k\n")
        self.installed("scratch")
        run = self.demo("uninstall", "--instance", "scratch", "--yes", script=repo / "demo.sh", **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue((repo / "runtime-data/api").exists())
        self.assertTrue((repo / "runtime-data/presenter-dev.key").exists())
        self.assertNotIn("mock mode", run.stdout)

    def test_556_an_option_never_takes_the_next_option_as_its_value(self):
        """#558: `--revision --dry-run` must not drop the dry run and run for real."""
        for args in (("model", "--revision", "--dry-run"), ("local", "--model", "--dry-run"),
                     ("local", "--instance", "--dry-run"), ("model", "--timeout", "--dry-run")):
            with self.subTest(args=args):
                run = self.demo(*args, FAKE_MODELS=served(NANO_MODEL), **self.recording())
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                self.assertIn(f"demo.sh: {args[1]} needs", run.stderr)
                self.assertEqual(self.changes(), "")

    def test_556_timeouts_are_decimal_and_bounded(self):
        """#559: 08m is eight minutes, not a bash octal error and an endless wait; 0 and absurd values are refused."""
        run = self.demo("model", "--timeout", "08m", "--dry-run", FAKE_MODELS=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("value too great", run.stderr)
        for bad in ("0", "0m", "99999999999999999999m"):
            with self.subTest(bad=bad):
                run = self.demo("model", "--timeout", bad, "--dry-run")
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                self.assertIn("--timeout must be", run.stderr)

    def test_556_next_steps_after_an_instance_name_that_instance(self):
        """#560: the printed Status and Stop act on the instance just deployed, not the default one."""
        run = self.demo("local", "--dry-run", "--instance", "scratch", "--api-port", "28100", "--web-port", "28181",
                        FAKE_MODELS=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Status: ./demo.sh status --instance scratch --api-port 28100 --web-port 28181", run.stdout)
        self.assertIn("Stop: ./demo.sh stop local --instance scratch --api-port 28100 --web-port 28181", run.stdout)
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL))
        self.assertIn("Status: ./demo.sh status    Stop: ./demo.sh stop", run.stdout)

    def test_556_a_dry_run_writes_no_log_file(self):
        """#562: --dry-run changes nothing, log files included."""
        for args in (("mock",), ("local",), ("setup",), ("model", "--device", "nano"), ("check-model",)):
            with self.subTest(args=args):
                extra = self.machine("z8") if args[0] == "setup" else {}
                run = self.demo(*args, "--dry-run", FAKE_MODELS=served(NANO_MODEL), **extra)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                logs = self.tmp / "logs"
                self.assertEqual(sorted(p.name for p in logs.rglob("*")) if logs.exists() else [], [])

    def test_556_update_restarts_with_the_model_and_zrt_mode_given(self):
        """#565: the restart after update keeps --model and --zrt-mode, like every other option."""
        repo, git = self.git_repo(("one", True), ("two", True))
        subprocess.run([*git, "-c", "advice.detachedHead=false", "checkout", "-q", "v0.0.0"], check=True)
        run = self.demo("update", "--dry-run", "--model", "qwen3-14b-fp8", "--zrt-mode", "user", script=repo / "demo.sh",
                        FAKE_RUNNING_IMAGE="aware-care-demo-api:local", FAKE_IMAGES="aware-care-demo-api:local",
                        **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertRegex(run.stdout, r"demo\.sh local .*--model qwen3-14b-fp8 --zrt-mode user")

    def test_556_troubleshooting_gives_a_colour_fix_that_works_with_force_color(self):
        """#563: FORCE_COLOR wins over NO_COLOR, so the documented fix for escape codes must not rely on NO_COLOR alone."""
        run = self.demo("--help", NO_COLOR="1", FORCE_COLOR="1")
        self.assertIn("\033[", run.stdout, "FORCE_COLOR still wins over NO_COLOR")
        self.assertNotIn("\033[", self.demo("--help", "--no-color", FORCE_COLOR="1").stdout)
        row = next(line for line in (ROOT / "docs/wiki/Troubleshooting.md").read_text().splitlines()
                   if "shows escape codes" in line)
        fix = row.rstrip(" |").rsplit("|", 1)[1]
        self.assertIn("--no-color", fix)
        self.assertIn("unset FORCE_COLOR", fix)


    # ------------------------------------------------------------------ QA #650: a second account on the shared Fury

    def second_account(self) -> dict[str, str]:
        """QA #650: the manager's account on the shared Fury: ZRT in user mode with its proxy on 8000 (serving nothing
        of ours), lingering off, no model unit of its own; the maintainer's ZRT serves the model on another port."""
        endpoint = self.zrt_service(NANO_MODEL)
        port = endpoint.rsplit(":", 1)[1]
        return {"FAKE_ZRT_MODE": "user", "FAKE_ZRT_PORT": "8000", "FAKE_PROXY_PORT": "8000", "FAKE_MODELS": served(),
                "FAKE_LISTEN_PORTS": f"22 8000 {port}", "FAKE_LINGER": "no", "QA_PORT": port, **self.machine("gb300")}

    def test_651_doctor_never_asks_you_to_serve_a_model_another_account_serves(self):
        """#651: the ZRT section said "./demo.sh setup (or model) serves it", lingering off "stops the model" and
        "./demo.sh model turns the watchdog on", while the Model section said "do not serve it again"."""
        env = self.second_account()
        run = self.demo("doctor", **env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        zrt = run.stdout.split("\nZRT\n")[1].split("\nModel\n")[0]
        self.assertNotIn("./demo.sh setup (or model) serves it", zrt)
        self.assertNotIn("Lingering is off", zrt)
        self.assertNotIn("./demo.sh model turns it on", zrt)
        self.assertIn(f"✓ ZRT on http://127.0.0.1:8000/v1 serves no model; port {env['QA_PORT']} serves it "
                      "(see Model, below)", zrt)
        self.assertIn("Lingering and the model's watchdog: nothing to do here (they matter to the account "
                      "that serves the model)", zrt)
        run = self.demo("status", **env)
        self.assertIn("Watchdog: nothing to do here (another account's ZRT serves the model)", run.stdout)
        self.assertNotIn("./demo.sh model turns it on", run.stdout)
        # your own model unit serves it: lingering and the watchdog matter again
        run = self.demo("doctor", FAKE_ENABLED="enabled", **env)
        self.assertIn("! Lingering is off: the model stops when you log out", run.stdout)


    def test_657_setup_shows_zrts_own_address_when_another_port_serves_the_model(self):
        """#657: setup's ZRT section showed the port it had found the model on as ZRT's configured address."""
        env = self.second_account()
        run = self.demo("setup", "--dry-run", script=self.setup_clone() / "demo.sh", **env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        zrt = run.stdout.split("\nZRT\n")[1].split("\nModel\n")[0]
        self.assertIn("✓ ZRT address: http://127.0.0.1:8000/v1 (from zrt config get proxy.port)", zrt)
        self.assertIn(f"ZRT on http://127.0.0.1:8000/v1 serves no model; port {env['QA_PORT']} serves it", zrt)
        self.assertIn(f"--zrt-base-url http://127.0.0.1:{env['QA_PORT']}/v1 ", run.stdout)  # the deploy still uses it


    def test_652_status_beside_another_accounts_demo_says_whose_it_is(self):
        """#652: status read the deployment record from your own (empty) data root: "Local: ? (commit ?), mode None"
        and "Data: <your empty folder>" while the maintainer's release ran."""
        run = self.demo("status", FAKE_RUNNING_IMAGE=self.RELEASE, FAKE_RELEASE="v0.19.4-demo.1",
                        FAKE_DATA_MOUNT="/home/bob/.local/share/aware-care-demo/data/local", **self.machine("gb300"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        local = run.stdout.split("\nLocal\n")[1]
        self.assertIn("✓ Local: the release v0.19.4-demo.1 from the deploy workflow", local)
        self.assertIn("runs here, readiness ", local)
        self.assertIn("Its data stays in /home/bob/.local/share/aware-care-demo", local)
        self.assertIn("./demo.sh setup --replace", local)
        self.assertNotIn("? (commit ?)", local)
        self.assertNotIn("mode None", local)
        self.assertNotIn(f"Data: {self.tmp}", local)


    def test_653_the_docker_group_fix_names_the_user_for_the_administrator(self):
        """#653: "Run: sudo usermod -aG docker $USER": the user is not a sudoer, and in the administrator's shell $USER
        is the administrator, who then adds themselves."""
        for args in (("local", "--dry-run"), ("doctor",)):
            with self.subTest(args=args):
                run = self.demo(*args, FAKE_DOCKER="denied", FAKE_MODELS=served(NANO_MODEL))
                out = run.stdout + run.stderr
                # #694: in the administrator block (local, setup) or doctor's own line
                self.assertTrue("An administrator adds you to the docker group, once" in out
                                or "Copy this block to an administrator:\n      sudo usermod -aG docker alice" in out, out)
                self.assertIn("sudo usermod -aG docker alice", out)
                self.assertNotIn("$USER", out)
        row = next(line for line in (ROOT / "README.md").read_text().splitlines() if "Docker is not usable" in line)
        self.assertNotIn("$USER", row)
        self.assertIn("sudo usermod -aG docker <user>", row)


    def test_654_beside_a_degraded_demo_setup_says_its_model_is_not_served(self):
        """#654: beside a demo that answered "degraded" (its model down), setup said "it may still be starting: try
        again in 2 minutes", which never helps."""
        env = {"FAKE_RUNNING_IMAGE": self.RELEASE, "FAKE_RELEASE": "v0.20.0-demo.1", "FAKE_READY": "1",
               "FAKE_READINESS": "degraded", "FAKE_MODELS": served(NANO_MODEL), **self.machine("gb10"),
               "FAKE_WEB_ENV": ',"AWARECARE_WEB_PORT=8180","AWARECARE_ORIGIN=http://127.0.0.1:18180"'}
        run = self.demo("setup", "--dry-run", **env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("! It answers degraded on 127.0.0.1:8180, not ready: it runs, but its model does not answer", run.stdout)
        self.assertIn("Fix: ./demo.sh status shows whether ZRT serves the model", run.stdout)
        self.assertNotIn("may still be starting", run.stdout)
        # no answer at all: it may still be starting
        run = self.demo("setup", "--dry-run", **{**env, "FAKE_READY": ""})
        self.assertIn("! It does not answer on 127.0.0.1:8180 yet", run.stdout)
        self.assertIn("it may still be starting", run.stdout)


    def test_655_uninstall_of_an_instance_keeps_the_instance_in_its_hint(self):
        """#655: after `uninstall --instance qa-prash` the hint named `./demo.sh uninstall --all`, which removes the
        default instance's containers: on the shared Fury the maintainer's running release."""
        root = self.tmp / "home/.local/share/scratch"
        (root / "state").mkdir(parents=True)
        for args in (("--dry-run",), ("--yes",)):
            with self.subTest(args=args):
                run = self.demo("uninstall", "--instance", "scratch", *args)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                hint = run.stdout.rstrip().splitlines()[-1]
                self.assertIn("./demo.sh uninstall --all --instance scratch", hint)
        hint = self.demo("uninstall", "--dry-run").stdout.rstrip().splitlines()[-1]
        self.assertTrue(hint.endswith("./demo.sh uninstall --all"), hint)


    def test_658_uninstall_help_and_readme_agree_on_what_all_adds(self):
        """#658: plain uninstall removed the data root with the model's serve script, yet its hint, --help and the
        README said --all removes the serve script; --help called the older images "generic images"."""
        hint = self.demo("uninstall", "--dry-run").stdout.rstrip().splitlines()[-1]
        self.assertIn("Also the model's settings and demo.sh's logs: ./demo.sh uninstall --all", hint)
        hint = self.demo("uninstall", "--dry-run", "--instance", "scratch").stdout.rstrip().splitlines()[-1]
        self.assertIn("Also the model unit, its settings and demo.sh's logs: ./demo.sh uninstall --all --instance scratch",
                      hint)
        row = next(line for line in self.demo("--help").stdout.splitlines() if line.strip().startswith("--all "))
        self.assertNotIn("generic", row)
        self.assertNotIn("serve script", row)
        readme = (ROOT / "README.md").read_text()
        row = next(line for line in readme.splitlines() if line.startswith("| `./demo.sh uninstall --all` |"))
        self.assertNotIn("serve script", row)
        row = next(line for line in readme.splitlines() if line.startswith("| `./demo.sh uninstall` |"))
        self.assertIn("serve script", row)


    def test_659_doctors_system_cache_fix_names_setup(self):
        """#659: doctor's fix for a model in the system ZRT's cache said "Run: ./demo.sh doctor --zrt-mode system";
        doctor serves nothing."""
        rev = self.tmp / "zrt-home/models/hf/Qwen/Qwen3.6-35B-A3B-FP8" / NANO_PINNED
        rev.mkdir(parents=True)
        (rev / "config.json").write_text("{}")
        groups = self.tmp / "bin/id"
        groups.write_text(f'#!/bin/sh\n[ "$1" = -nG ] && {{ echo "alice docker zrt"; exit 0; }}\nexec {shutil.which("id")} "$@"\n')
        groups.chmod(0o755)
        run = self.demo("doctor", "--zrt-mode", "user", **self.machine("gb10"))
        self.assertIn("✗ The system ZRT already has this model", run.stdout)
        self.assertIn("Run: ./demo.sh setup --zrt-mode system", run.stdout)
        self.assertNotIn("./demo.sh doctor --zrt-mode", run.stdout)


    def test_660_doctor_offers_local_only_when_zrt_serves_the_model(self):
        """#660: with the model downloaded but not served, doctor's verdict said "Ready for ./demo.sh setup (or
        ./demo.sh local)"; local stops with "ZRT does not serve"."""
        run = self.demo("doctor", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@{NANO_PINNED}"), **self.machine("gb10"))
        verdict = run.stdout.split("\nVerdict\n")[1]
        self.assertIn("✓ Ready for ./demo.sh setup (it serves the downloaded model, then builds and deploys the app)", verdict)
        self.assertNotIn("./demo.sh local", verdict)
        run = self.demo("doctor", FAKE_MODELS=served(NANO_MODEL), **self.machine("gb10"))
        self.assertIn("✓ Ready for ./demo.sh setup (or ./demo.sh local)", run.stdout)


    def test_661_replace_has_its_own_section_and_whose_demo_reads_plainly(self):
        """#661: setup --replace printed its note under Ports, and whose demo it was nested parentheses:
        "(the release ... from the deploy workflow (account bob); its data stays ...)"."""
        repo = self.setup_clone()
        env = {**self.machine("gb10"), "FAKE_RUNNING_IMAGE": self.RELEASE, "FAKE_RELEASE": "v0.20.0-demo.1",
               "FAKE_DATA_MOUNT": "/home/bob/.local/share/aware-care-demo/data/local", "FAKE_MODELS": served(NANO_MODEL)}
        run = self.demo("setup", "--replace", "--dry-run", script=repo / "demo.sh", **env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("--replace:", run.stdout.split("\nPorts\n")[1].split("\n\n")[0])
        self.assertIn("\nReplace\n  ! --replace: aware-care-demo-api and aware-care-demo-web run the release "
                      "v0.20.0-demo.1 from the deploy workflow, run by bob", run.stdout)
        run = self.demo("uninstall", "--dry-run", **env)
        self.assertIn("(the release v0.20.0-demo.1 from the deploy workflow, run by bob; its data stays in", run.stdout)
        self.assertNotIn("(account", run.stdout)


    def test_662_stop_dry_run_says_whose_demo_it_would_stop(self):
        """#662: stop --dry-run beside another account's demo printed only the docker commands."""
        run = self.demo("stop", "--dry-run", **self.bob())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("They run the ./demo.sh instance of bob; its data stays in /home/bob/.local/share/aware-care-demo.",
                      run.stdout)
        self.assertNotIn("They run", self.demo("stop", "--dry-run", FAKE_RUNNING_IMAGE="aware-care-demo-api:local").stdout)


    def test_663_help_matches_the_model_wait_and_where_instance_options_go(self):
        """#663: --help said --timeout's default is 15m Nano, 8m Fury (since #644 the usual wait, then on while the
        model loads, 60m at most) and marked --instance, --api-port and --web-port as local only."""
        out = self.demo("--help").stdout
        self.assertIn("then on only while the model still loads, 60m at most", out)
        self.assertNotIn("(e.g. 20m; default 15m Nano, 8m Fury)", out)
        for opt in ("--instance <name>", "--api-port <n>", "--web-port <n>"):
            row = next(line for line in out.splitlines() if line.strip().startswith(opt))
            self.assertNotIn("local:", row)
        self.assertIn("setup, local, status, open, stop, uninstall and fresh", out)
        self.assertLessEqual(max(len(line) for line in out.splitlines()), 120)


    def sampler_line(self, root: Path) -> str:
        """#678: the runbook's crontab line for a data root (section 10b), as the deploy tool writes it."""
        return (f"* * * * * /usr/bin/flock -n {root}/telemetry/sampler.lock /usr/bin/python3 "
                f"{root}/telemetry/power_sampler.py --out {root}/data/local/power >> {root}/telemetry/sampler.log 2>&1")

    def test_678_setup_and_local_keep_the_power_sampler_running_themselves(self):
        """#678 (owner decision, 28 Oct 2026): the telemetry page measures the device's energy, and so its cost per
        consultation, only while the GPU power sampler runs. setup and local now keep it running themselves (the deploy
        tool adds its crontab line once and starts it) in a Telemetry step before Open it, instead of printing the line
        for the user to add; a rerun adds nothing; a dry run prints the command and the line; a crontab that cannot be
        written is a note with its fix, never a failed setup."""
        repo = self.setup_clone()
        z8 = {**self.machine("z8"), "FAKE_MODELS_AFTER": served(NANO_MODEL)}
        root = self.tmp / "home/.local/share/aware-care-demo"
        run = self.demo("setup", script=repo / "demo.sh", **z8)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = run.stdout
        self.assertIn("\nTelemetry\n  ✓ Power sampler on: a crontab line now keeps it running (a GPU power reading every "
                      "second for the telemetry page)\n", out)
        self.assertLess(out.index("outcome: SUCCEEDED"), out.index("\nTelemetry\n"))
        self.assertLess(out.index("\nTelemetry\n"), out.index("\nOpen it\n"))
        self.assertNotIn("Telemetry energy", out)  # #681's hint is gone: setup does it
        self.assertIn("deploy\npower-sampler\n", self.log("deploy.log"))
        # A rerun (the app already runs, its line is there) adds nothing.
        again = self.demo("setup", script=repo / "demo.sh", FAKE_RUNNING_IMAGE="aware-care-demo-api:local",
                          FAKE_WD_TIMER="on", FAKE_SAMPLER="kept", **z8)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("\nApp\n", again.stdout)
        self.assertIn("\nTelemetry\n  ✓ Power sampler on: a crontab line keeps it running (a GPU power reading every "
                      "second for the telemetry page)\n", again.stdout)
        # A crontab that cannot be written: a note with its fix; setup still ends with Open it.
        failed = self.demo("setup", script=repo / "demo.sh", FAKE_RUNNING_IMAGE="aware-care-demo-api:local",
                           FAKE_WD_TIMER="on", FAKE_SAMPLER="failed", **z8)
        self.assertEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertIn("! Power sampler off: its crontab line could not be added (crontab - failed: You are not allowed "
                      "to use this program), so the telemetry page shows the energy and the device's cost as not "
                      "measured\n    Fix: make crontab usable for alice (an administrator installs cron), then rerun "
                      "./demo.sh setup\n", failed.stdout)
        self.assertIn("\nOpen it\n", failed.stdout)
        # A dry run (the real deploy tool, reading the crontab only) prints the command and the line it would add.
        dry = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FAKE_STARTED="")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn(f"\nTelemetry\n    $ python3 infra/deploy/nano_deploy.py --data-root {root} power-sampler\n"
                      "    It adds this line to your crontab once (it keeps the GPU power sampler running for the "
                      f"telemetry page):\n    {self.sampler_line(root)}\n", dry.stdout)
        dry = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL), FAKE_STARTED="",
                        FAKE_CRONTAB=self.sampler_line(root))
        self.assertIn("    Your crontab already has the power sampler's line; nothing to add.\n", dry.stdout)

    def test_678_status_and_doctor_show_the_power_sampler(self):
        """#678: status (for your own local deployment) and doctor say whether a crontab line keeps this data root's
        sampler running and how old its last reading is."""
        root = self.tmp / "home/.local/share/aware-care-demo"
        (root / "state").mkdir(parents=True)
        (root / "state/current.json").write_text(json.dumps({"release_tag": "local", "app_commit": "e" * 40,
                                                             "mode": "local", "model_id": NANO_MODEL}))
        ours = {"FAKE_RUNNING_IMAGE": "aware-care-demo-api:local", "FAKE_MODELS": served(NANO_MODEL)}
        off = "Power sampler: off, so the telemetry page shows energy as not measured (./demo.sh setup or local turns it on)"
        self.assertIn(off, self.demo("status", **ours).stdout.split("\nLocal\n")[1])
        doctor = self.demo("doctor", FAKE_MODELS=served(NANO_MODEL)).stdout
        self.assertIn(f"\nTelemetry\n    {off}\n", doctor)
        kept = {**ours, "FAKE_CRONTAB": "# a comment naming " + str(root) + "/telemetry/power_sampler.py\n"
                + self.sampler_line(root)}
        self.assertIn("! Power sampler: its crontab line is there, but it has written no reading yet\n"
                      f"    Fix: cron starts it within a minute; if this stays, {root}/telemetry/sampler.log says why",
                      self.demo("status", **kept).stdout)
        power = root / "data/local/power"
        power.mkdir(parents=True)
        reading = power / "20261028T18.csv"
        reading.write_text("1793210000000,512.30\n")
        for command in ("status", "doctor"):
            with self.subTest(command):
                out = self.demo(command, **kept).stdout
                self.assertRegex(out, r"✓ Power sampler: on \(a crontab line keeps it running; last reading [0-9]+ s ago\)")
        old = time.time() - 600
        os.utime(reading, (old, old))
        self.assertRegex(self.demo("status", **kept).stdout,
                         r"! Power sampler: its crontab line is there, but its last reading is 10m0[0-9]s old")
        # Another data root's line (a name that only starts the same) does not count.
        other = {**ours, "FAKE_CRONTAB": self.sampler_line(Path(f"{root}-2"))}
        self.assertIn(off, self.demo("status", **other).stdout)
        # Someone else's demo: no sampler line for it (its data root is not yours).
        self.assertNotIn("Power sampler", self.demo("status", **self.bob()).stdout.split("\nLocal\n")[1])

    def test_678_uninstall_removes_the_power_samplers_crontab_line_first_and_keeps_the_others(self):
        """#678: uninstall (and uninstall --all) removes this data root's crontab line, and the comment the deploy tool
        wrote, before anything else; every other line stays. A dry run only prints the command."""
        repo = self.tree()
        shutil.copytree(ROOT / "infra", repo / "infra", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        self.installed()
        root = (self.tmp / "home/.local/share/aware-care-demo").resolve()
        crontab = self.tmp / "crontab"
        others = ["17 3 * * 1 /usr/bin/python3 /home/x/monitoring.py collect",
                  f"@reboot /usr/bin/python3 {root}/ops/boot_check.py >> {root}/ops/boot-check.log 2>&1"]
        mine = [f"# Aware Care (#678): the GPU power sampler for the telemetry page of {root}; ./demo.sh uninstall "
                "removes it", self.sampler_line(root)]
        crontab.write_text("\n".join([*others, *mine]) + "\n")
        env = {"FAKE_CRONTAB_FILE": str(crontab), "FAKE_RUNNING_IMAGE": "aware-care-demo-api:local", **self.recording()}
        dry = self.demo("uninstall", "--dry-run", script=repo / "demo.sh", **env)
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        listed = dry.stdout.split("What it removes")[1]
        self.assertIn("- the GPU power sampler's crontab line (the sampler stops)\n"
                      f"    $ python3 infra/deploy/nano_deploy.py --data-root {root} power-sampler --remove\n", listed)
        self.assertLess(listed.index("power sampler"), listed.index("the containers"))
        self.assertEqual(crontab.read_text(), "\n".join([*others, *mine]) + "\n")
        for args in (("--yes",), ("--all", "--yes")):
            with self.subTest(args=args):
                crontab.write_text("\n".join([*others, *mine]) + "\n")
                self.installed()
                run = self.demo("uninstall", *args, script=repo / "demo.sh", **env)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("✓ Removed the GPU power sampler's crontab line (the sampler stops)", run.stdout)
                self.assertEqual(crontab.read_text(), "\n".join(others) + "\n")
        # Nothing to remove: no line, no item.
        self.installed()
        self.assertNotIn("power sampler", self.demo("uninstall", "--dry-run", script=repo / "demo.sh", **env).stdout)

    def test_665_open_it_hints_and_the_model_start_fit_a_narrow_terminal(self):
        """#665: a second instance's Status and Stop hints shared one 165-character line, and the model's start line
        was about 200 characters long."""
        run = self.demo("local", "--dry-run", "--instance", "qa-prash", "--api-port", "28100", "--web-port", "28180",
                        FAKE_MODELS=served(NANO_MODEL))
        self.assertIn("  Status: ./demo.sh status --instance qa-prash --api-port 28100 --web-port 28180\n"
                      "  Stop: ./demo.sh stop local --instance qa-prash --api-port 28100 --web-port 28180\n", run.stdout)
        run = self.model_run("--timeout", "2", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"),
                             FAKE_ACTIVE="activating", FAKE_SUB="start")
        start = run.stdout.split("\nStart\n")[1]
        self.assertIn("    Model start: about 6 min here; a first start in a fresh ZRT takes up to 25 min (it builds the GPU "
                      "kernels).\n", start)
        self.assertIn("    It gives up after 2s (--timeout).\n", start)
        self.assertIn(f"  → Starting {NANO_MODEL} ({NANO_REPO}@main) ...", start)
        self.assertLessEqual(max(len(line) for line in start.splitlines() if "→" in line or "usually" in line), 100)


    def test_666_no_watchdog_for_a_model_unit_that_is_not_enabled(self):
        """#666: a leftover model unit, never enabled (an earlier setup stopped at "Failed to connect to bus"), got a
        watchdog when ZRT already served the model ("restarts the unit when the model dies": it never runs)."""
        unit = self.tmp / "home/.config/systemd/user/aware-care-zrt-model.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("x\n")
        run = self.model_run(FAKE_MODELS=served(NANO_MODEL))  # FAKE_ENABLED: disabled
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("Watchdog", run.stdout)
        self.assertFalse((self.tmp / "home/.config/systemd/user/aware-care-zrt-watchdog.timer").exists())


    def test_667_uninstall_never_says_data_stays_that_it_deletes(self):
        """#667: as the account the deploy workflow deploys with, uninstall said the release's "data stays in <your
        data root>" and then deleted that data root."""
        root = self.tmp / "home/.local/share/aware-care-demo"
        (root / "state").mkdir(parents=True)
        import getpass
        env = {"FAKE_RUNNING_IMAGE": self.RELEASE, "FAKE_RELEASE": "v0.20.0-demo.1",
               "FAKE_DATA_MOUNT": f"{root}/data/local", "USER": getpass.getuser()}  # the data root's owner
        run = self.demo("uninstall", "--dry-run", **env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn(f"its data stays in {root}", run.stdout)
        self.assertIn("(the release v0.20.0-demo.1 from the deploy workflow; its data is your own data root, which "
                      "uninstall removes below)", run.stdout)
        self.assertIn(f"- {root} (the app's data", run.stdout)
        # stop keeps it: there it stays
        run = self.demo("stop", **env)
        self.assertIn(f"its data stays in {root}", run.stdout)


    def test_668_uninstall_all_names_the_release_images_in_one_short_command(self):
        """#668: on the Fury "What stays" listed 64 release image IDs on one line of about 900 characters."""
        ids = " ".join(f"{n:012x}" for n in range(64))
        run = self.demo("uninstall", "--all", "--dry-run", FAKE_RELEASE_IMAGES=ids)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        line = next(x for x in run.stdout.splitlines() if "release images" in x)
        self.assertIn("The release images the deploy workflow pulled (64)", line)
        self.assertIn("docker image rm $(docker images -q 'ghcr.io/your-github-user/aware-care/*')", run.stdout)
        self.assertNotIn(f"{63:012x}", run.stdout)
        self.assertLessEqual(max(len(x) for x in run.stdout.splitlines() if "release images" in x or "docker images -q" in x), 110)


    def test_651_setup_does_not_tell_you_to_run_setup(self):
        """#651: during setup the ZRT section's fix said "./demo.sh setup (or model) serves it": the command running."""
        run = self.demo("setup", "--dry-run", script=self.setup_clone() / "demo.sh", **self.machine("z8"))
        zrt = run.stdout.split("\nZRT\n")[1].split("\nModel\n")[0]
        self.assertIn("Fix: nothing: setup serves it in the next steps", zrt)
        self.assertNotIn("./demo.sh setup (or model)", zrt)
        self.assertIn("Fix: ./demo.sh setup (or model) serves it", self.demo("doctor", **self.machine("z8")).stdout)


    def test_670_status_shows_your_own_release_as_your_deployment(self):
        """#670: as the account the deploy workflow deploys with, status called its own release someone else's demo
        ("Yours instead: ./demo.sh setup --replace") and dropped its record (a regression of #652)."""
        import getpass
        root = self.tmp / "home/.local/share/aware-care-demo"
        (root / "state").mkdir(parents=True)
        (root / "state/current.json").write_text(json.dumps({"release_tag": "v0.20.1-demo.1", "app_commit": "e" * 40,
                                                             "mode": "local", "model_id": NANO_MODEL}))
        run = self.demo("status", FAKE_RUNNING_IMAGE=self.RELEASE, FAKE_RELEASE="v0.20.1-demo.1",
                        FAKE_DATA_MOUNT=f"{root}/data/local", USER=getpass.getuser(), **self.machine("gb300"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        local = run.stdout.split("\nLocal\n")[1]
        self.assertIn(f"✓ Local: v0.20.1-demo.1 (commit {'e' * 12}), mode local, model {NANO_MODEL}", local)
        self.assertIn(f"Data: {root}", local)
        self.assertNotIn("Yours instead", local)

    # ------------------------------------------------------------------ owner decisions T1-T5 (#694-#698), QA #702

    def groups_stand_in(self) -> None:
        """`id -nG` answers FAKE_GROUPS (default alice docker: outside the zrt group); every other call is the real id."""
        groups = self.tmp / "bin/id"
        groups.write_text(f'#!/bin/sh\n[ "$1" = -nG ] && {{ echo "${{FAKE_GROUPS:-alice docker}}"; exit 0; }}\n'
                          f'exec {shutil.which("id")} "$@"\n')
        groups.chmod(0o755)

    def test_694_setup_prints_one_administrator_block_before_any_download(self):
        """#694 (T1): before any download, setup checks every step an administrator must do once (docker group, zrt
        group, lingering, the login) and prints them in one copy-paste block with the account's name, then stops."""
        repo = self.setup_clone()
        self.groups_stand_in()
        hidden = self.tmp / "zrt-home"  # /opt/hp/zrt on the Fury: drwxrws--- root:zrt, not enterable outside the group
        (hidden / "models").mkdir(parents=True)
        if os.geteuid() != 0:
            hidden.chmod(0)
            self.addCleanup(hidden.chmod, 0o755)
        all_three = {"FAKE_DOCKER": "denied", "FAKE_LINGER": "no", **self.machine("gb300"), **self.recording()}
        run = self.demo("setup", "--zrt-mode", "user", script=repo / "demo.sh", **all_three)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        err = run.stderr
        self.assertIn("✗ An administrator must do 2 things for alice, once, before setup can go on", err)
        self.assertIn("Docker: alice is not in the docker group", err)
        if os.geteuid() != 0:
            self.assertIn("      sudo usermod -aG docker,zrt alice\n      sudo loginctl enable-linger alice\n", err)
            self.assertIn("only the zrt group may read the system ZRT's models", err)
            self.assertIn("Run: ./demo.sh setup --zrt-mode system", err)
        self.assertIn("Then log out, log in again over SSH as alice (ssh alice@<this machine>; not sudo then su)", err)
        self.assertEqual(err.count("Copy this block"), 1, "one block")
        self.assertNotIn("\nModel\n", run.stdout)
        self.assertNotIn("pull", self.zrt_calls())
        self.assertEqual(self.changes(), "")
        # the zrt group alone (#702 case 3: the system cache it cannot read may hold the model)
        if os.geteuid() != 0:
            run = self.demo("model", "--device", "fury", "--zrt-mode", "user", script=repo / "demo.sh",
                            **self.machine("gb300"), **self.recording())
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertIn("      sudo usermod -aG zrt alice\n", run.stderr)
            self.assertNotIn("pull", self.zrt_calls())
        # nothing to do: one green line
        run = self.demo("setup", "--dry-run", script=repo / "demo.sh", FAKE_GROUPS="alice docker zrt", **self.machine("gb300"))
        self.assertIn("✓ Nothing for an administrator to do (docker group, login session, lingering)", run.stdout)
        # doctor shows the same block and goes on
        run = self.demo("doctor", FAKE_DOCKER="denied", FAKE_LINGER="no", **self.machine("gb300"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("\nAdministrator\n  ✗ An administrator must do 2 things for alice, once, before setup can go on\n",
                      run.stdout)
        self.assertIn("Copy this block to an administrator:\n      sudo usermod -aG docker alice\n"
                      "      sudo loginctl enable-linger alice\n", run.stdout)
        self.assertIn("Run: ./demo.sh setup\n", run.stdout)

    def test_696_setup_without_docker_access_beside_a_running_demo_opens_it(self):
        """#696 (T3): the manager was outside the docker group, so the running demo was invisible to demo.sh. A demo that
        answers on the web port counts as running: "It's already running: open it here", and no administrator block."""
        run = self.demo("setup", FAKE_DOCKER="denied", FAKE_READY="1", **self.machine("gb300"), **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("✓ It's already running: open it here\n    A demo answers on 127.0.0.1:8180 (Docker is not usable "
                      "for you, so demo.sh cannot tell whose it is)", run.stdout)
        self.assertIn("ssh -N -p 2222 -L 18180:127.0.0.1:8180 alice@192.0.2.3", run.stdout)
        self.assertNotIn("Administrator", run.stdout + run.stderr)
        self.assertEqual(self.changes(), "")

    def test_695_open_prints_the_tunnel_and_the_address_of_the_demo_that_runs(self):
        """#695 (T2): ./demo.sh open reprints the tunnel and the address for this login and host, at any time."""
        web_env = ',"AWARECARE_WEB_PORT=8180","AWARECARE_ORIGIN=http://127.0.0.1:18180"'
        cases = (({"FAKE_RUNNING_IMAGE": self.RELEASE, "FAKE_RELEASE": "v0.20.4-demo.1", "FAKE_READY": "1"},
                  "✓ The demo runs here: The release v0.20.4-demo.1 from the deploy workflow"),
                 ({"FAKE_RUNNING_IMAGE": "aware-care-demo-api:local", "FAKE_READY": "1"},
                  "✓ The demo runs here: Your own ./demo.sh instance (aware-care-demo-api, aware-care-demo-web)"),
                 ({"FAKE_DOCKER": "denied", "FAKE_READY": "1"},
                  "✓ The demo runs here: A demo answers on 127.0.0.1:8180 (Docker is not usable for you"))
        for env, says in cases:
            with self.subTest(says=says):
                run = self.demo("open", FAKE_WEB_ENV=web_env, **env, **self.recording())
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn(says, run.stdout)
                self.assertIn("✓ It answers ready on 127.0.0.1:8180", run.stdout)
                self.assertIn("ssh -N -p 2222 -L 18180:127.0.0.1:8180 alice@192.0.2.3", run.stdout)
                self.assertIn("Then open:  http://127.0.0.1:18180", run.stdout)
                self.assertEqual(self.changes(), "")
        run = self.demo("open", "--instance", "qa", "--web-port", "28180")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("✗ Nothing answers on 127.0.0.1:28180: the demo does not run here", run.stderr)
        self.assertIn("Run: ./demo.sh setup --instance qa --web-port 28180", run.stderr)

    def test_697_the_download_says_how_far_it_got_and_how_long_is_left(self):
        """#697 (T4): long steps show time estimates and progress ("Download: about 10 min left")."""
        store = self.tmp / "zrt-home/models/hf" / NANO_REPO
        run = self.model_run(FAKE_ZRT_MODELS=zrt_models("hf:Qwen/Qwen3-32B@main"), FAKE_PULL_DIR=str(store),
                             AWARECARE_DEMO_STATUS_SECONDS="1", FAKE_MODELS_AFTER=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertRegex(run.stdout, r"\ds: Download: \d+\.\d of 37\.49 GB, about \d+ min left")
        self.assertNotIn("\x1b", run.stdout, "plain without a terminal")

    def test_698_fresh_backs_up_uninstalls_all_and_sets_up_again(self):
        """#698 (T5): ./demo.sh fresh backs up the data with the README's tar command, runs uninstall --all (never
        --with-model) and setup again, and says where the backup is."""
        repo = self.setup_clone()
        root = self.tmp / "home/.local/share/aware-care-demo"
        (root / "state").mkdir(parents=True)
        (root / "state/current.json").write_text("{}")
        day = time.strftime("%Y%m%d")
        backup = self.tmp / f"home/aware-care-data-{day}.tar.gz"
        run = self.demo("fresh", "--dry-run", script=repo / "demo.sh", **self.machine("gb300"), **self.recording())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"$ tar -czf {backup} -C {self.tmp}/home/.local/share aware-care-demo", run.stdout)
        self.assertIn("Aware Care · uninstall --all · dry run", run.stdout)
        self.assertIn("Aware Care · setup", run.stdout)
        self.assertNotIn("the downloaded model hf:", run.stdout)  # never --with-model
        self.assertFalse(backup.exists())
        self.assertTrue(root.exists())
        # without --yes and without a terminal: nothing
        run = self.demo("fresh", script=repo / "demo.sh", **self.machine("gb300"))
        self.assertIn("Nothing changed (--yes answers the question).", run.stdout)
        self.assertTrue(root.exists())
        # for real: the backup holds the data, then uninstall --all removes it, then setup runs
        stand_ins = {"FAKE_MODELS": served(NANO_MODEL), "FAKE_DEPLOY_LOG": str(self.tmp / "deploy.log"),
                     "FAKE_BUILD_LOG": str(self.tmp / "build.log"), "AWARECARE_DEMO_MODEL_WAIT": "2"}
        run = self.demo("fresh", "--yes", script=repo / "demo.sh", **self.machine("gb300"), **self.recording(), **stand_ins)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"✓ Backed up {root} to {backup}", run.stdout)
        listing = subprocess.run(["tar", "-tzf", str(backup)], capture_output=True, text=True).stdout
        self.assertIn("aware-care-demo/state/current.json", listing)
        self.assertIn("Aware Care · uninstall --all", run.stdout)
        self.assertIn("Aware Care · setup", run.stdout)
        self.assertIn(f"Your earlier data is in {backup}", run.stdout)
        self.assertNotIn("zrt -m system remove", self.zrt_calls())
        # a failed backup stops it before anything is removed
        (root / "state").mkdir(parents=True, exist_ok=True)
        if os.geteuid() != 0:
            home = self.tmp / "home"
            home.chmod(0o500)
            self.addCleanup(home.chmod, 0o755)
            run = self.demo("fresh", "--yes", script=repo / "demo.sh", **self.machine("gb300"), **stand_ins)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertIn(f"✗ The backup of {root} failed, so nothing was removed", run.stderr)
            self.assertNotIn("Aware Care · uninstall", run.stdout)
            home.chmod(0o755)
            self.assertTrue(root.exists())
        run = self.demo("fresh", "--with-model")
        self.assertEqual(run.returncode, 2)
        self.assertIn("never removes the model", run.stderr)

    def test_702_case1_status_says_when_the_containers_are_gone(self):
        """#702 (case 1): after the release's containers were removed by hand, status still showed a green "Local:"."""
        root = self.tmp / "home/.local/share/aware-care-demo"
        (root / "state").mkdir(parents=True)
        (root / "state/current.json").write_text(json.dumps({"release_tag": "v0.20.4-demo.1", "app_commit": "e" * 40,
                                                             "mode": "local", "model_id": NANO_MODEL}))
        run = self.demo("status", FAKE_MODELS=served(NANO_MODEL))  # no containers
        local = run.stdout.split("\nLocal\n")[1]
        self.assertIn("! Local: v0.20.4-demo.1 is recorded here, but its containers are gone (removed outside demo.sh?)", local)
        self.assertIn("Fix: Run ./demo.sh setup to deploy it again (its data is kept)", local)
        self.assertNotIn("✓ Local:", local)

    def test_702_case1_uninstall_says_it_stops_someone_elses_demo(self):
        """#702 (case 1): uninstall --all as a second account listed the release's containers as one line among others."""
        run = self.demo("uninstall", "--all", "--dry-run", FAKE_RUNNING_IMAGE=self.RELEASE, FAKE_RELEASE="v0.20.4-demo.1",
                        FAKE_READY="1", FAKE_DATA_MOUNT="/home/bob/.local/share/aware-care-demo/data/local")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("! This stops the demo that runs here and answers ready now (the release v0.20.4-demo.1 from the "
                      "deploy workflow", run.stdout)
        self.assertIn("Fix: to use it rather than remove it, answer N and open it: ./demo.sh open", run.stdout)

    def test_702_case5_a_model_started_by_hand_gets_its_unit_and_watchdog(self):
        """#702 (case 5): a model started with `zrt service start` showed as served; nothing said it has no unit and no
        watchdog. status and doctor say so; model (and setup) add them without starting a second copy."""
        mine = {"FAKE_MODELS": served(NANO_MODEL), "FAKE_ZRT_SERVICES": self.service_row(os.getpid(), "Ready"),
                **self.machine("gb10")}
        says = "! ZRT serves the model, but it was started outside demo.sh: no unit and no watchdog"
        self.assertIn(says, self.demo("status", **mine).stdout)
        self.assertIn(says, self.demo("doctor", **mine).stdout)
        run = self.model_run(**mine)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(says, run.stdout)
        calls = self.log("systemctl.log")
        self.assertIn("systemctl --user enable aware-care-zrt-model.service", calls)
        self.assertIn("systemctl --user enable --now aware-care-zrt-watchdog.timer", calls)
        self.assertTrue((self.tmp / "home/.config/systemd/user/aware-care-zrt-model.service").exists())
        self.assertNotIn("pull", self.zrt_calls())
        # another account's process (PID 1 is root's): not ours to adopt
        theirs = {**mine, "FAKE_ZRT_SERVICES": self.service_row(1, "Ready")}
        self.assertNotIn(says, self.demo("status", **theirs).stdout)

    def test_702_case6_no_download_or_start_when_another_model_fills_the_gpu(self):
        """#702 (case 6): another model filled the Fury's GPU (151.6 GB on port 8000); setup downloaded and started anyway."""
        other = ("│ 0 │ 4411 │ hf:Qwen/Qwen3.8-Flash-Next-FP8@236dfdf │ http://127.0.0.1:8000 │ Ready │ 151.6 GB (VRAM) │ 1h ago │\n"
                 "│   │      │ Qwen/Qwen3.8-Flash-Next-FP8            │                       │       │                 │        │")
        full = {"FAKE_GPU_MEM": "262144, 213000", "FAKE_GPU_APPS": f"{os.getpid()}, /usr/bin/python3, 151600 MiB\n",
                "FAKE_ZRT_SERVICES": other, **self.machine("gb300")}
        run = self.demo("model", "--device", "fury", **full, **self.recording())
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"✗ The GPU has 48 GB free, and {FURY_MODEL} asks for about 52 GB (0.20 of 256 GB), so it would not "
                      "start", run.stderr)
        self.assertIn("Run: zrt -m system service stop hf:Qwen/Qwen3.8-Flash-Next-FP8@236dfdf", run.stderr)
        self.assertNotIn("pull", self.zrt_calls())
        self.assertEqual(self.changes(), "")
        run = self.demo("model", "--device", "fury", "--dry-run", **{**full, "FAKE_GPU_MEM": "262144, 10000"})
        self.assertIn("✓ GPU memory: 246 GB free; the model asks for about 52 GB (0.20 of 256 GB)", run.stdout)

    def test_702_case7_update_never_moves_back_and_accepts_any_origin(self):
        """#702 (case 7): in a fork without the newer tags, update planned a checkout of an older release; the
        local-changes stop named git status rather than one command. This public copy accepts any origin (a fork or a
        copy publishes its own v* tags), so update never refuses because of where origin points."""
        repo, git = self.git_repo(("one", True), ("two", True))
        origin = self.tmp / "fork"
        subprocess.run(["git", "clone", "-q", str(repo), str(origin)], check=True)
        subprocess.run(["git", "-C", str(origin), "tag", "-d", "v0.1.0"], check=True, capture_output=True)
        subprocess.run([*git, "remote", "set-url", "origin", str(origin)], check=True)
        subprocess.run([*git, "tag", "-d", "v0.1.0"], check=True, capture_output=True)
        subprocess.run([*git, "tag", "v0.1.0"], check=True)  # this checkout: v0.1.0; the fork's newest: v0.0.0
        run = self.demo("update", "--dry-run", script=repo / "demo.sh")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("checkout v0.0.0", run.stdout)
        self.assertIn("✓ Already on the newest release origin has: v0.1.0", run.stdout)
        self.assertNotIn("origin is", run.stdout + run.stderr)
        self.assertNotIn("set-url", run.stdout + run.stderr)
        # a public clone's origin URL (the dry run fetches nothing): the same, no refusal
        subprocess.run([*git, "remote", "set-url", "origin", "https://github.com/example/aware-care.git"], check=True)
        run = self.demo("update", "--dry-run", script=repo / "demo.sh")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("git -C", run.stdout)
        self.assertNotIn("origin is", run.stdout + run.stderr)
        (repo / "notes.txt").write_text("mine\n")
        run = self.demo("update", script=repo / "demo.sh")
        self.assertIn(f"Run: git -C {repo} switch -c my-changes && git -C {repo} commit -qam 'My changes'", run.stderr)

    def test_704_a_rerun_while_the_model_loads_waits_for_it(self):
        """#704 (case 8): someone took a slow first start for a failure and reran model (or setup) while it loaded. The
        GPU check counted the model's own memory and stopped ("The GPU has 50 GB free"); before #702 the rerun restarted
        the unit and threw the load away. Now it waits for the start already under way."""
        loading = {"FAKE_ZRT_MODELS": zrt_models(f"hf:{NANO_REPO}@{NANO_PINNED}"), "FAKE_ACTIVE": "activating",
                   "FAKE_SUB": "start", "FAKE_ZRT_SERVICES": self.service_row(os.getpid(), "Loading"),
                   "FAKE_GPU_MEM": "262144, 240000", "FAKE_GPU_APPS": f"{os.getpid()}, VLLM::EngineCore, 52000 MiB\n"}
        run = self.demo("model", "--device", "fury", "--timeout", "2", FAKE_SYSTEMCTL_LOG=str(self.tmp / "systemctl.log"),
                        **loading, **self.machine("gb300"))
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)  # --timeout 2: it gives up after waiting
        self.assertIn(f"✓ The model is still starting: ZRT's service for it (PID {os.getpid()}, Loading)", run.stdout)
        self.assertIn("Model start: 0s so far (usually about 2 min here)", run.stdout)
        self.assertNotIn("The GPU has", run.stderr)
        self.assertNotIn("restart", self.log("systemctl.log"))
        self.assertNotIn("pull", self.zrt_calls())
        # a service that loads outside demo.sh's unit: no second copy
        run = self.demo("model", "--device", "fury", **{**loading, "FAKE_ACTIVE": "inactive"}, **self.machine("gb300"),
                        **self.recording())
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"✗ ZRT is already starting {FURY_MODEL} outside demo.sh's unit (PID {os.getpid()}, Loading", run.stderr)
        self.assertEqual(self.changes(), "")

    def test_704_setup_says_started_outside_once(self):
        mine = {"FAKE_MODELS": served(NANO_MODEL), "FAKE_ZRT_SERVICES": self.service_row(os.getpid(), "Ready"),
                **self.machine("gb10")}
        run = self.demo("setup", "--dry-run", **mine)
        self.assertEqual((run.stdout + run.stderr).count("started outside demo.sh"), 1, run.stdout)

    def test_702_case8_the_dry_run_says_how_long_the_model_start_takes(self):
        run = self.demo("model", "--device", "fury", "--dry-run", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@{NANO_PINNED}"))
        self.assertIn("Model start: about 2 min here; a first start in a fresh ZRT takes up to 25 min", run.stdout)


if __name__ == "__main__":
    unittest.main()
