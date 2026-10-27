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
FURY_MODEL = "qwen3.8-flash-next-fp8"

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
    */api/v1/health/ready) [ -n "${FAKE_READY:-}" ] && printf '{"readiness":"ready"}'; exit 0 ;;
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
        echo zrt-stand-in "$@" ;;
  *) echo zrt-stand-in "$@" ;;
esac
"""

# systemctl: `show -p <property> --value` answers from FAKE_ACTIVE, FAKE_SUB, FAKE_RESTARTS, FAKE_SINCE (the unit's
# InactiveExitTimestamp) and FAKE_ENTERED (its ActiveEnterTimestamp); a start or restart of the model unit creates
# FAKE_STARTED. #640: `is-enabled` and `is-active` answer FAKE_ENABLED and FAKE_ACTIVE for the model unit, and for the
# watchdog's timer "enabled" and "active" when FAKE_WD_TIMER=on (else "disabled", "inactive").
SYSTEMCTL = """\
#!/bin/sh
case "$1 $2" in
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

LOGINCTL = "#!/bin/sh\necho yes\n"
# df: free space (doctor's and setup's disk checks) is FAKE_FREE_GB, never the runner's own disk (#549: a CI runner
# had 13 GB free, so setup stopped at the model's disk check)
DF = "#!/bin/sh\necho Avail\necho \"${FAKE_FREE_GB:-2000}G\"\n"
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
FURY_REPO = "Qwen/Qwen3.8-Flash-Next-FP8"


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
    return "\n".join(line for line in lines if "the checkout has local changes" not in line)


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
                           ("uv", UV), ("node", NODE), ("npm", NPM), ("ss", SS), ("df", DF)):
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

    def cuda_root(self, *dirs: str, name: str = "cuda-root") -> Path:
        root = self.tmp / name
        root.mkdir(exist_ok=True)
        for d in dirs:
            nvcc = root / d / "bin/nvcc"
            nvcc.parent.mkdir(parents=True)
            nvcc.write_text("#!/bin/sh\n")
            nvcc.chmod(0o755)
        return root

    def demo(self, *args: str, script: Path = SCRIPT, **env: str) -> subprocess.CompletedProcess:
        self.assertTrue(script.exists(), f"{script} is missing")
        return subprocess.run(["bash", str(script), *args], env={**self.env, **env}, capture_output=True, text=True,
                              timeout=60, stdin=subprocess.DEVNULL)

    # ------------------------------------------------------------------ device detection

    def test_detects_the_device_from_the_served_model(self):
        for model, device in ((NANO_MODEL, "Nano"), (FURY_MODEL, "Fury")):
            with self.subTest(device=device):
                run = self.demo("local", "--dry-run", FAKE_MODELS=served(model))
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn(f"Device: ZGX {device} (ZRT serves {model})", run.stdout)
                self.assertIn(f"demo-zgx-{device.lower()}.json", run.stdout)

    def test_falls_back_to_the_gpu_name_then_asks_for_the_model(self):
        run = self.demo("local", "--dry-run", FAKE_GPU="NVIDIA GB300")
        self.assertIn("Device: ZGX Fury (GPU NVIDIA GB300)", run.stdout)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(f"ZRT does not serve {FURY_MODEL}", run.stderr)
        self.assertIn("zrt pull hf:Qwen/Qwen3.8-Flash-Next-FP8@", run.stderr)
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
        forms = {"nano": [f"{NANO_REPO}@main", NANO_REPO, NANO_REPO.lower(), f"hf:{NANO_REPO}@main",
                          f"hf:{NANO_REPO}@{NANO_PINNED}", f"/opt/hp/zrt/models/hf/{NANO_REPO}/main"],
                 "fury": [f"{FURY_REPO}@main", FURY_REPO.upper(), f"hf:{FURY_REPO}@v2"]}
        for device, ids in forms.items():
            for served_id in ids:
                with self.subTest(served=served_id):
                    run = self.demo("local", "--dry-run", FAKE_MODELS=served("Qwen/Qwen2.5-0.5B-Instruct", served_id))
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn(f"Device: ZGX {device.capitalize()} (ZRT serves {served_id})", run.stdout)
                    model = NANO_MODEL if device == "nano" else FURY_MODEL
                    self.assertIn(f"ZRT serves {model} as {served_id}", run.stdout)
                    self.assertNotIn("zrt pull", run.stdout + run.stderr)

    def test_another_revision_is_a_note_never_a_failure(self):
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(f"{NANO_REPO}@main"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Note: serving revision main; this app was qualified on 95a723d…", run.stdout)
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_MODEL))  # our label, ZRT says nothing more
        self.assertIn("ZRT does not say which revision it serves", run.stdout)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_the_revision_behind_a_name_comes_from_zrt(self):
        services = f"│ 1 │ hf:{NANO_REPO}@main │ {NANO_REPO} │ - │ Ready │"
        run = self.demo("local", "--dry-run", FAKE_MODELS=served(NANO_REPO), FAKE_ZRT_SERVICES=services)
        self.assertIn("Note: serving revision main;", run.stdout)
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
        self.assertIn("Note: serving revision main; this app was qualified on 95a723d…", run.stdout)

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
        self.assertIn("Note: serving revision main; this app was qualified on 95a723d…", dry.stdout)
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
        self.assertIn("GPU memory: processes on the GPU now: 4242, python3, 30000 MiB", run.stderr)
        self.assertIn(f"zrt logs tail {NANO_MODEL} --lines 50", run.stderr)
        self.assertIn("vllm: engine core died", run.stderr)

    def test_model_wait_gives_up_at_the_timeout_with_status_lines(self):
        run = self.model_run("--timeout", "2", FAKE_ZRT_MODELS=zrt_models(f"hf:{NANO_REPO}@main"),
                             FAKE_ACTIVE="activating", FAKE_SUB="start", FAKE_JOURNAL="Loading safetensors shards")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("0s: unit activating (start); Loading safetensors shards", run.stdout)
        self.assertIn(f"✗ ZRT did not serve {NANO_MODEL} within 2s", run.stderr)
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
        self.assertIn(f"✗ ZRT did not serve {NANO_MODEL} within 3s", run.stderr)
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

    # ------------------------------------------------------------------ prerequisites

    def test_docker_without_permission_names_the_group_fix(self):
        run = self.demo("local", "--dry-run", FAKE_DOCKER="denied", FAKE_MODELS=served(NANO_MODEL))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("Docker is not usable without sudo", run.stderr)
        self.assertIn("sudo usermod -aG docker $USER", run.stderr)
        self.assertIn("log out and back in", run.stderr)
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
        self.assertIn("check: docker buildx version", run.stderr)
        self.assertIn("or the standalone docker-buildx program on your PATH (check: docker-buildx version)", run.stderr)
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
        self.assertIn("through ZRT's proxy (./demo.sh model)", run.stdout)
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
        self.assertIn(f"! Nothing on port 8000 lists the model; it is served on port {port}, so demo.sh uses "
                      f"{endpoint}/v1", run.stdout)
        self.assertIn("No need to serve it again with ./demo.sh model.", run.stdout)
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
        self.assertIn("./demo.sh local --zrt-port <port>   (or --zrt-url http://127.0.0.1:<port>/v1)", run.stderr)
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
        self.assertEqual(len(lines), 3, out)
        build, key, deploy = lines
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

    # ------------------------------------------------------------------ deployments demo.sh did not build

    def test_a_workflow_deployment_is_never_replaced_or_stopped(self):
        image = "ghcr.io/your-github-user/aware-care/aware-care-api@sha256:" + "a" * 64
        log = self.tmp / "docker.log"
        for args in (("local", "--dry-run"), ("stop", "local"), ("uninstall", "--yes")):
            with self.subTest(args=args):
                run = self.demo(*args, FAKE_MODELS=served(NANO_MODEL), FAKE_RUNNING_IMAGE=image,
                                FAKE_DOCKER_LOG=str(log))
                self.assertNotEqual(run.returncode, 0, run.stdout)
                # #632: local says the demo already runs (here not ready, so it fails); stop and uninstall refuse
                self.assertIn("The running demo does not answer ready" if args[0] == "local"
                              else "demo.sh leaves them alone", run.stderr)
                # local: run a copy on other ports; #617: stop and uninstall name your own instance instead
                self.assertIn("--instance my-demo --api-port 28100 --web-port 28180" if args[0] == "local"
                              else f"./demo.sh {' '.join(args[:1] + ('local',) * (args[0] == 'stop'))} --instance <name>",
                              run.stderr)
                self.assertNotIn("build_images.sh", run.stdout)
        self.assertFalse(log.exists(), "no container may be removed")

    def test_632_local_and_setup_beside_a_ready_release_say_how_to_open_it(self):
        """#632: a second account on the Fury ran local beside the maintainer's release and was only told to set up
        another instance. Now it learns the demo already runs, how to open it (the release's own origin port), and
        that a second instance is only for its own copy; nothing is built, deployed or removed."""
        image = "ghcr.io/your-github-user/aware-care/aware-care-api@sha256:" + "a" * 64
        log = self.tmp / "docker.log"
        for cmd in ("local", "setup"):
            with self.subTest(cmd=cmd):
                run = self.demo(cmd, "--no-color", FAKE_MODELS=served(NANO_MODEL), FAKE_RUNNING_IMAGE=image,
                                FAKE_DOCKER_LOG=str(log), FAKE_RELEASE="v0.19.0-demo.1", FAKE_READY="1", **self.machine("gb10"),
                                FAKE_WEB_ENV=',"AWARECARE_WEB_PORT=8180","AWARECARE_ORIGIN=http://127.0.0.1:18180"')
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("✓ The demo already runs on this machine: release v0.19.0-demo.1 "
                              "(aware-care-demo-api, aware-care-demo-web)", run.stdout)
                self.assertIn("You can use it as it is: nothing to set up.", run.stdout)
                self.assertIn("✓ It answers ready on 127.0.0.1:8180", run.stdout)
                self.assertIn("ssh -N -p 2222 -L 18180:127.0.0.1:8180 alice@192.0.2.3", run.stdout)
                self.assertIn("Then open exactly:  http://127.0.0.1:18180", run.stdout)
                self.assertIn(f"./demo.sh {cmd} --instance my-demo --api-port 28100 --web-port 28180", run.stdout)
                self.assertNotIn("build_images.sh", run.stdout)
                self.assertNotIn("Model", run.stdout.split("Already running")[1])
        self.assertFalse(log.exists(), "nothing may be built, deployed or removed")

    def test_634_another_accounts_default_instance_is_never_replaced_or_stopped(self):
        """#634: container names are the same for every account. bob's ./demo.sh instance (images
        aware-care-demo-*:local, data in bob's home) was rebuilt over by alice's local and removed by her stop."""
        bob = {"FAKE_RUNNING_IMAGE": "aware-care-demo-api:local", "FAKE_MODELS": served(NANO_MODEL),
               "FAKE_DATA_MOUNT": "/home/bob/.local/share/aware-care-demo/data/local"}
        log = self.tmp / "docker.log"
        run = self.demo("local", "--no-color", FAKE_DOCKER_LOG=str(log), FAKE_READY="1", **bob)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("✓ The demo already runs on this machine: the instance of bob "
                      "(aware-care-demo-api, aware-care-demo-web)", run.stdout)
        self.assertIn("You can use it as it is (you share its data)", run.stdout)
        self.assertIn("Then open exactly:  http://127.0.0.1:18180", run.stdout)
        self.assertIn("./demo.sh local --instance my-demo --api-port 28100 --web-port 28180", run.stdout)
        self.assertIn("only bob updates or stops it", run.stdout)
        self.assertNotIn("build_images.sh", run.stdout)
        for args in (("stop", "local"), ("uninstall", "--yes")):
            with self.subTest(args=args):
                run = self.demo(*args, FAKE_DOCKER_LOG=str(log), **bob)
                self.assertNotEqual(run.returncode, 0, run.stdout)
                self.assertIn("are the ./demo.sh instance of bob (data in /home/bob/.local/share/aware-care-demo); "
                              "demo.sh leaves them alone", run.stderr)
                self.assertIn("Only bob changes or stops that instance", run.stderr)
        run = self.demo("stop", FAKE_DOCKER_LOG=str(log), **bob)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Nothing of yours runs (aware-care-demo-api and aware-care-demo-web are the ./demo.sh instance "
                      "of bob", run.stdout)
        self.assertFalse(log.exists(), "nothing of bob's may be built, replaced or removed")
        # alice's own instance (her data root) is hers to stop, as before
        own = {**bob, "FAKE_DATA_MOUNT": str(self.tmp / "home/.local/share/aware-care-demo/data/local")}
        run = self.demo("stop", "local", FAKE_DOCKER_LOG=str(log), **own)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("rm -f aware-care-demo-api", log.read_text())

    def test_636_uninstall_goes_ahead_once_a_release_is_stopped(self):
        """#636: with the release's containers removed, uninstall --all still refused ("the live deployment ... runs")
        because the data root's state/current.json names its image; nothing said how to get past it."""
        image = "ghcr.io/your-github-user/aware-care/aware-care-api@sha256:" + "a" * 64
        root = self.tmp / "home/.local/share/aware-care-demo"
        (root / "state").mkdir(parents=True)
        (root / "state/current.json").write_text(f'{{\n  "api_image": "{image}",\n  "release": "v0.19.2-demo.1"\n}}\n')
        # running: refused, with the way to stop it
        run = self.demo("uninstall", "--all", "--yes", FAKE_RUNNING_IMAGE=image)
        self.assertNotEqual(run.returncode, 0, run.stdout)
        self.assertIn("A release (maintainers only): docker rm -f aware-care-demo-api aware-care-demo-web", run.stderr)
        self.assertNotIn("its deploy workflow;", run.stderr)
        self.assertTrue(root.exists())
        # stopped (no containers): it removes the data root and the record with it
        run = self.demo("uninstall", "--all", "--yes")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"✓ Removed {root}", run.stdout)
        self.assertFalse(root.exists())

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
                     "uninstall", "--port", "--dry-run",
                     "--revision", "--no-color", "doctor", "check-model", "--model <label>", "--zrt-mode user|system",
                     "--device nano|fury|auto", "--instance", "--api-port", "--web-port", "--all", "--with-model",
                     "--yes", "AWARECARE_DEMO_INSTANCE", "AWARECARE_DEMO_DATA_ROOT", "AWARECARE_DEMO_API_PORT",
                     "AWARECARE_DEMO_WEB_PORT"):
            self.assertIn(word, run.stdout)
        # The commands form an aligned table: every description starts in the same column.
        lines = run.stdout.split("Commands\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(len(lines), 10, run.stdout)
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
        run = self.model_run(FAKE_MODELS=served(NANO_MODEL))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ZRT already serves", run.stdout)
        self.assertIn("Watchdog on:", run.stdout.split("\nWatchdog\n")[1])
        self.assertIn("systemctl --user enable --now aware-care-zrt-watchdog.timer",
                      (self.tmp / "systemctl.log").read_text())
        self.assertFalse(self.wd_state.exists(), "a person ran model: a fresh restart count")
        self.assertTrue((self.tmp / "home/.config/systemd/user/aware-care-zrt-watchdog.timer").exists())
        # installed as this checkout has it and on: a rerun changes nothing
        (self.tmp / "systemctl.log").unlink()
        run = self.model_run(FAKE_MODELS=served(NANO_MODEL), FAKE_WD_TIMER="on")
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
                self.assertIn(f"! Watchdog: on, but it gave up after 3 restarts within an hour (last restart {when}); "
                              "./demo.sh model serves the model again", run.stdout)
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

    def test_uninstall_all_refuses_beside_a_workflow_deployment(self):
        repo = self.tree()
        paths = self.installed("scratch")
        image = "ghcr.io/your-github-user/aware-care/aware-care-api@sha256:" + "a" * 64
        run = self.demo("uninstall", "--all", "--yes", "--instance", "scratch", script=repo / "demo.sh",
                        FAKE_CONTAINERS=f"aware-care-demo-api={image} scratch-api=scratch-api:local",
                        **self.recording())
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        # #602: it says why --all is refused (what it removes for every instance here, which the live deployment
        # uses) and what to do instead, not the generic "run your own copy beside it" hint.
        err = re.sub(r"\s+", " ", run.stderr)
        self.assertIn("uninstall --all is refused: --all also removes what every instance on this machine shares, and "
                      "the live deployment aware-care-demo uses it", err)
        for shared in ("the model unit aware-care-zrt-model.service", "the model's serve script "
                       "~/.local/share/aware-care-demo/zrt", "the model's settings ~/.config/aware-care-demo",
                       "the images aware-care-api:local and aware-care-web:local",
                       "demo.sh's logs and check-model reports"):
            self.assertIn(shared, err)
        self.assertIn("To remove only scratch: ./demo.sh uninstall --instance scratch", err)
        # #636: no workflow stops a release; the refusal names the command that does
        self.assertIn("To remove everything: stop the live deployment aware-care-demo first, then rerun", err)
        self.assertIn("docker rm -f aware-care-demo-api aware-care-demo-web; its deploy workflow puts it back later",
                      err)
        self.assertNotIn("--instance my-demo", err)
        self.assertEqual(self.changes(), "")
        self.assertTrue(all(path.exists() for path in paths))
        # --with-model also names the downloaded model
        run = self.demo("uninstall", "--all", "--with-model", "--yes", "--instance", "scratch", script=repo / "demo.sh",
                        FAKE_CONTAINERS=f"aware-care-demo-api={image} scratch-api=scratch-api:local",
                        **self.recording())
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("the downloaded model in ZRT's cache", re.sub(r"\s+", " ", run.stderr))
        self.assertEqual(self.changes(), "")

    def test_617_uninstall_and_stop_beside_the_live_deployment_say_what_to_remove_instead(self):
        """#617 (QA #613): the plain `uninstall --all` on the maintainer's machine (the default instance runs the workflow
        deployment) gives #602's reason, and uninstall and stop never advise running a copy on deploy ports."""
        repo = self.tree()
        image = "ghcr.io/your-github-user/aware-care/aware-care-api@sha256:" + "a" * 64
        live = {"FAKE_CONTAINERS": f"aware-care-demo-api={image}", **self.recording()}
        run = self.demo("uninstall", "--all", "--yes", script=repo / "demo.sh", **live)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        err = re.sub(r"\s+", " ", run.stderr)
        self.assertIn("uninstall --all is refused: --all also removes what every instance on this machine shares, and "
                      "the live deployment aware-care-demo uses it", err)
        self.assertIn("To remove only your own instance: ./demo.sh uninstall --instance <name>", err)
        for args, hint in ((("uninstall", "--yes"), "./demo.sh uninstall --instance <name>"),
                           (("stop", "local"), "./demo.sh stop local --instance <name>")):
            with self.subTest(args=args):
                run = self.demo(*args, script=repo / "demo.sh", **live)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                err = re.sub(r"\s+", " ", run.stderr)
                self.assertIn("demo.sh leaves them alone", err)
                self.assertIn(hint, err)
        for args in (("uninstall", "--all", "--yes"), ("uninstall", "--yes"), ("stop", "local")):
            run = self.demo(*args, script=repo / "demo.sh", **live)
            self.assertNotIn("Run your own copy", run.stderr, args)
            self.assertNotIn("--api-port", run.stderr, args)
        self.assertEqual(self.changes(), "")

    # ------------------------------------------------------------------ QA repl-03, repl-06, repl-09

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
        self.assertEqual(list(self.sections(run.stdout)), ["Checks", "Model", "Build", "Deploy", "Open it"])
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
                self.assertIn(f"Then open exactly:  {url}", block)
                self.assertIn("use 127.0.0.1, not localhost", block)
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
        self.assertIn("Fix: Once, with sudo:  sudo usermod -aG docker $USER", ANSI.sub("", fails.stderr))
        self.assertIn("\x1b[", self.demo("--help", FORCE_COLOR="1").stdout)

    def test_a_failure_prints_the_fix_then_the_log_path_and_its_last_lines(self):
        run = self.model_run(FAKE_ZRT_MODELS=zrt_models("hf:Qwen/Qwen3-32B@main"), FAKE_PULL_FAIL="1")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"→ Downloading {NANO_REPO}@{NANO_PINNED}", run.stdout)
        self.assertIn("✗ zrt pull failed", run.stderr)
        self.assertIn("    Fix: See the last lines of the log below, then rerun ./demo.sh model", run.stderr)
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
    log.write(" ".join(a for a in args if a in ("presenter-key", "deploy", "status")) + "\\n")
if "deploy" in args:
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
        self.assertEqual(self.log("deploy.log").split(), ["status", "presenter-key", "deploy"])
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
        self.assertEqual(self.log("deploy.log").split(), ["status"])
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
        self.assertIn("✗ Docker is not usable without sudo (your user is not in the docker group)", run.stderr)
        self.assertIn("Fix: Once, with sudo:  sudo usermod -aG docker $USER", run.stderr)
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
        self.assertEqual(self.log("deploy.log").split(), ["status"])  # read-only
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
        build, files, key, deploy = self.dollar_lines(out)
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
        the home page's buttons, and since #640 `model` installs and turns on the model's watchdog."""
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
        self.assertIn("Result: FAIL: advisory only", run.stdout)
        run = self.demo("check-model", FAKE_MODELS=served("qwen3-14b-fp8"), FAKE_NO_REPORT="1", **self.machine("24gb"))
        self.assertEqual(run.returncode, 1)
        self.assertIn("The check did not run", run.stderr)
        run = self.demo("check-model", FAKE_MODELS=served("Prash_0.30.0"), **self.machine("24gb"))
        self.assertEqual(run.returncode, 1)
        self.assertIn("Serve it first: ./demo.sh model", run.stderr)

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


if __name__ == "__main__":
    unittest.main()
