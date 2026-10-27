#!/usr/bin/env python3
"""Deploy, roll back and inspect the Aware Care demo on an HP ZGX device (M12; R34, R37, R38, R40).

Used by .github/workflows/deploy-nano.yml on the Nano's self-hosted runner and by deploy-fury.yml on the Fury's
(ADR-018, `--config infra/deploy/demo-zgx-fury.json`), and by an operator from a checkout of the deployed release tag
(see spec/engineering/08-delivery-and-nano-runbook.md). Standard library only. The configuration names the device
(shown by the web gateway) and, optionally, the API's per-device files inside the image.

  deploy    Start a release's API and web images in an explicit mode, check
            readiness and one synthetic flow, then keep it or roll back.
  rollback  Redeploy the deployment recorded in state/previous.json.
  status    Print the recorded deployments, container states and readiness.
  presenter-key  Create the presenter key (ADR-005 option A) under
            <data_root>/secrets/presenter.key, mode 600; never printed. With it, the
            gateway's presenter path /presenter-api/ is enabled (#487: one port, one origin).

Guarantees:
- Deployments are serialized by an flock on <data_root>/deploy.lock.
- #578: in local mode the checks (the test consultation calls the device model) hold the device's model lock
  (scripts/dev/with_model_lock.sh, #544), taken before any container changes; a busy model fails the deploy then.
- Containers use host networking and bind 127.0.0.1 only, so container
  loopback is the host loopback where ZRT listens (ADR-010). No port is published.
  The web gateway serves both roles on one port (#487); presenter access is refused
  unless it binds loopback (ADR-005: presenter access never reaches a network).
- ZRT and GPU configuration are never changed. Local mode only reads
  GET <zrt>/models before any container changes, and a failed local readiness or
  flow check fails the deployment. Nothing falls back to mock mode.
- #591: a deployment that passed its checks is kept only once state/current.json and state/previous.json are written
  (both or neither); until then the parked containers stay, and a failed write restores them.
- Runtime data lives in <data_root>/data/<mode>, outside Git and the images.
- Evidence records statuses, digests and timings, never health content.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import http.client
import ipaddress
import json
import os
import platform
import re
import shutil
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flow_check  # noqa: E402  (sibling module, standard library only)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_model_ids():
    """The API's model-ID matcher (#528; standard library only), shared so the preflight and the app agree."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("aware_care_model_ids",
                                                  REPO_ROOT / "apps/api/app/runtime/model_ids.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve the module by name
    spec.loader.exec_module(module)
    return module


model_ids = _load_model_ids()

EVIDENCE_SCHEMA = "aware-care-deployment-evidence/1"
ARCH_ALIASES = {"arm64": "aarch64", "aarch64": "aarch64", "amd64": "x86_64", "x86_64": "x86_64"}
CONTAINER_DATA_DIR = "/var/lib/aware-care/data"
# Time budget (#294). The deploy job's timeout-minutes (deploy-nano.yml, deploy-fury.yml: 40) must stay clearly above
# the worst case of the waits below, or the runner kills the job before the rollback has run. Worst case, in seconds:
#   lock wait 300 + pulls 2 x 210 + preflight ~30 (ZRT /models 10) + model lock wait 300 (#578, local mode)
#   + park 2 x ~25 (docker stop -t 20) + start ~20 + readiness 65 (60 s + one 5 s probe)
#   + flow check 160 (guidance 90 + 60, cleanup 10) + presenter check 140 (120, cleanup 2 x 10)
#   + automatic rollback ~385 (restore ~20 + readiness 65 + flow 160 + presenter 140)
#   = ~1890 s (31.5 min), plus ~2 min of checkout and registry login: ~34 min < 40 min.
# Other docker commands are bounded by DOCKER_TIMEOUT_SECONDS each but normally take well under a second. A cancel
# (SIGINT/SIGTERM from the runner) restores the parked containers without re-checking them, so it fits in the
# runner's few seconds of grace before SIGKILL.
LOCK_WAIT_SECONDS = 300
PULL_TIMEOUT_SECONDS = 210
DOCKER_TIMEOUT_SECONDS = 120
FLOW_CHECK_OVERHEAD_SECONDS = 60   # flow check budget = guidance timeout + this
PRESENTER_CHECK_SECONDS = 120
# #578: the longest wait for the device's model lock (another AI job using the model) before a deploy gives up;
# AWARE_CARE_MODEL_LOCK_WAIT overrides it (an operator's ./demo.sh local, never the workflows).
MODEL_LOCK_WAIT_SECONDS = 300
MODEL_LOCK_SCRIPT = REPO_ROOT / "scripts/dev/with_model_lock.sh"


# ADR-018: device names reach nginx and the browser, so only a plain character set is accepted.
DEVICE_NAME = re.compile(r"[A-Za-z0-9 .-]{1,40}")
# #315/#487: the origin is rendered into the gateway's device script, so only a plain origin is accepted.
BROWSER_ORIGIN = re.compile(r"https?://[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?")
# #487: the gateway's bind address (network.bind_host): an IP literal or "localhost". Presenter access needs loopback.
BIND_HOST = re.compile(r"[0-9A-Fa-f:.]{2,45}|localhost")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
API_FILE_ENV = {"model_manifest": "AWARECARE_MODEL_MANIFEST", "device_inventory": "AWARECARE_DEVICE_INVENTORY",
                "telemetry_pricing": "AWARECARE_TELEMETRY_PRICING"}
DEVICE_FILES = {"AWARECARE_DEVICE_INVENTORY": "device-inventory.json",
                "AWARECARE_TELEMETRY_PRICING": "telemetry-pricing.json"}
DEVICE_FILES_MOUNT = "/run/aware-care/device"
# #549: optional in the device files: the served model's manifest when it is a candidate on this machine
# (hardware.py device-files), so the API does not show another device's qualification
DEVICE_FILES_OPTIONAL = {"AWARECARE_MODEL_MANIFEST": "model-manifest.json"}


class DeployError(RuntimeError):
    pass


class DeployInterrupted(BaseException):
    """SIGTERM (a workflow cancel or timeout): raised like KeyboardInterrupt so the deployment can restore what it
    parked before it exits (#294)."""


def _raise_interrupted(signum, _frame):
    raise DeployInterrupted(f"interrupted by signal {signal.Signals(signum).name}")


@contextlib.contextmanager
def signals_deferred():
    """Ignore SIGINT/SIGTERM while the parked deployment is restored, so a second signal cannot cut it short."""
    previous = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, signal.SIG_IGN)
    except ValueError:  # not the main thread (tests): nothing to defer
        pass
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def loopback_base_url(raw: str, name: str = "zrt.base_url") -> str:
    """The same rule as the API's settings (#150, ADR-014): ZRT on this device's loopback, parsed, never
    prefix-matched. Checked before any container starts, so a bad configuration cannot reach the API."""
    from urllib.parse import urlsplit
    url = str(raw).strip().rstrip("/")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise DeployError(f"{name} must be a loopback ZRT endpoint") from exc
    host = parts.hostname or ""
    bracketed = f"[{host}]" if ":" in host else host
    if (parts.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"} or port is None
            or parts.username is not None or parts.password is not None or parts.netloc != f"{bracketed}:{port}"
            or parts.query or parts.fragment):
        raise DeployError(f"{name} must be a loopback ZRT endpoint (http://127.0.0.1:<port>/…, no user info)")
    return url


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    print(f"[nano-deploy] {message}", flush=True)


def docker(*args: str, check: bool = True, capture: bool = True,
           timeout: float = DOCKER_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(["docker", *args], text=True, capture_output=capture, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DeployError(f"docker {args[0]} did not finish within {timeout:.0f}s") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-1:] if capture else []
        raise DeployError(f"docker {args[0]} failed: {' '.join(detail) or result.returncode}")
    return result


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    if config.get("document_kind") != "deployment_configuration":
        raise DeployError(f"{path} is not a deployment configuration")
    return config


# #587: the checks reach this host's gateway and ZRT directly, never through an HTTP proxy from the environment
# (no_proxy rarely lists ::1), as boot_check.py does.
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_status(url: str, timeout: float = 5.0) -> tuple[int | None, dict | None]:
    try:
        with NO_PROXY.open(urllib.request.Request(url, headers={"Accept": "application/json"}),
                           timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except ValueError:
            return exc.code, None
    except (OSError, http.client.HTTPException, ValueError):  # URLError, timeouts, resets, truncated bodies
        return None, None


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def container_state(name: str) -> dict | None:
    result = docker("container", "inspect", name, check=False)
    if result.returncode != 0:
        return None
    info = json.loads(result.stdout)[0]
    return {"name": name, "status": info["State"]["Status"], "running": info["State"]["Running"],
            "exit_code": info["State"]["ExitCode"], "image_id": info["Image"],
            "labels": {k: v for k, v in (info["Config"].get("Labels") or {}).items() if k.startswith("aware-care.")}}


def model_base_url(name: str) -> str | None:
    """The ZRT URL a running API container was given (AWARECARE_MODEL_BASE_URL), or None (#535)."""
    result = docker("container", "inspect", "-f", "{{json .Config.Env}}", name, check=False)
    try:
        env = json.loads(result.stdout) if result.returncode == 0 else []
    except ValueError:
        return None
    return next((e.split("=", 1)[1] for e in env or [] if e.startswith("AWARECARE_MODEL_BASE_URL=")), None)


def remove_container(name: str) -> None:
    if container_state(name):
        docker("rm", "-f", name)


def private_dir(path: Path) -> Path:
    """Create `path` (and missing parents) private to the deploying user, and make it private if it already exists
    (#152): `mkdir(mode=0o700)` neither changes an existing folder nor applies to parents, so a folder first created
    by another tool under a permissive umask (the Fury's power sampler, umask 002) stayed group- and world-readable."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def harden_data_root(settings: "Settings", mode: str | None = None) -> None:
    """The data root, `data/` and `data/<mode>` hold runtime databases and health payloads (synthetic in this demo):
    only the deploying user may enter them. Applied at every deployment, so a host that drifted is corrected."""
    private_dir(settings.root)
    private_dir(settings.root / "data")
    if mode:
        private_dir(settings.root / "data" / mode)


@contextlib.contextmanager
def deploy_lock(root: Path):
    private_dir(root)
    with open(root / "deploy.lock", "w") as handle:
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise DeployError("another deployment holds the device lock")
                log("waiting for another deployment to finish")
                time.sleep(5)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextlib.contextmanager
def model_lock(description: str):
    """#578: hold the device's model lock (#544) through scripts/dev/with_model_lock.sh, so the same lock file and the
    same "waiting for the model (...)" message as every other AI job. A helper shell sources it, takes the lock and
    says "held"; it keeps the lock until this process closes its stdin (also when this process dies). Nested use (the
    caller already holds the lock, AWARE_CARE_MODEL_LOCK_HELD) does not wait. Raises DeployError when the model stays
    busy for MODEL_LOCK_WAIT_SECONDS."""
    if not MODEL_LOCK_SCRIPT.is_file():
        raise DeployError(f"the model lock helper {MODEL_LOCK_SCRIPT} is missing")
    env = {**os.environ}
    env.setdefault("AWARE_CARE_MODEL_LOCK_WAIT", str(MODEL_LOCK_WAIT_SECONDS))
    # $0 is not the helper's path, so sourcing it only defines model_lock_acquire
    script = '. "$1"; model_lock_acquire "$2" || exit $?; echo held; read -r _ || true'
    holder = subprocess.Popen(["bash", "-c", script, "nano_deploy-model-lock", str(MODEL_LOCK_SCRIPT), description],
                              env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                              start_new_session=True)
    try:
        if holder.stdout.readline().strip() != "held":
            code = holder.wait(timeout=30)
            raise DeployError(f"another AI job kept the device model busy (model lock "
                              f"{env.get('AWARE_CARE_MODEL_LOCK', '/tmp/aware-care-model.lock')}, exit {code}); "
                              "wait for it to finish, then deploy again")
        log("holding the device's model lock for the checks")
        yield
    finally:
        with contextlib.suppress(OSError):
            holder.stdin.close()
        try:
            holder.wait(timeout=10)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait()


class Settings:
    def __init__(self, config: dict, args: argparse.Namespace):
        network = config["network"]
        self.config = config
        self.environment = config["environment"]
        self.instance = args.instance or config["instance"]
        self.root = Path(os.path.expanduser(args.data_root or config["data_root_default"])).resolve()
        self.api_port = args.api_port or network["api_port"]
        self.web_port = args.web_port or network["web_port"]
        self.origin = args.origin or network["browser_origin"]
        if not BROWSER_ORIGIN.fullmatch(self.origin):
            raise DeployError("browser_origin must be a plain http(s) origin such as http://127.0.0.1:18180")
        # #487 (ADR-005 amendment): one gateway, one port and one origin for both roles; the presenter API is the path
        # /presenter-api/ of the same gateway. A configuration or command line from before (presenter_port,
        # presenter_origin, --presenter-port, --presenter-origin) stays readable: the values are ignored, and named.
        self.legacy_presenter = sorted(
            {f"network.{k}" for k in ("presenter_port", "presenter_origin", "presenter_tunnel_example") if k in network}
            | {f"--{k.replace('_', '-')}" for k in ("presenter_port", "presenter_origin") if getattr(args, k, None)})
        self.bind_host = str(getattr(args, "bind_host", None) or network.get("bind_host") or "127.0.0.1")
        if not BIND_HOST.fullmatch(self.bind_host):
            raise DeployError("bind_host must be an IP address or localhost, such as 127.0.0.1")
        # #535: --zrt-base-url (demo.sh: AWARECARE_ZRT_URL or --zrt-url, or a ZRT service endpoint it found) replaces
        # the configured zrt.base_url, under the same loopback rule; the API receives it as AWARECARE_MODEL_BASE_URL.
        override = getattr(args, "zrt_base_url", None)
        self.zrt_base_url_source = "--zrt-base-url" if override else "config zrt.base_url"
        self.zrt_base_url = (loopback_base_url(override, "--zrt-base-url") if override
                             else loopback_base_url(config["zrt"]["base_url"]))
        self.readiness_path = config["readiness"]["path"]
        self.readiness_timeout = config["readiness"]["timeout_seconds"]
        expected = getattr(args, "expected_arch", None) or config["platform"].split("/")[1]
        self.expected_arch = ARCH_ALIASES.get(expected, expected)
        # ADR-018: the device this environment runs on, and the API's per-device files inside the image.
        device = dict(config.get("device") or {"name": "HP ZGX Nano", "short_name": "ZGX Nano"})
        # #537: any NVIDIA machine (infra/deploy/demo-generic.json): demo.sh names it from DMI.
        for key in ("name", "short_name"):
            if getattr(args, f"device_{key}", None):
                device[key] = getattr(args, f"device_{key}")
        for key in ("name", "short_name"):
            if not DEVICE_NAME.fullmatch(str(device.get(key, ""))):
                raise DeployError(f"device.{key} must be 1-40 letters, digits, spaces, dots or hyphens")
        self.device_name, self.device_short_name = device["name"], device["short_name"]
        self.api_files = {API_FILE_ENV[k]: v for k, v in (config.get("api_files") or {}).items()}
        # #537: a host directory with this machine's device-inventory.json and telemetry-pricing.json (written by
        # demo.sh), mounted read-only; the API reads them instead of the image's files.
        self.device_files: Path | None = None
        if getattr(args, "device_files", None):
            self.device_files = Path(os.path.expanduser(args.device_files)).resolve()
            for name in DEVICE_FILES.values():
                if not (self.device_files / name).is_file():
                    raise DeployError(f"--device-files {self.device_files} has no {name}")
            self.api_files.update({env: f"{DEVICE_FILES_MOUNT}/{name}" for env, name in DEVICE_FILES.items()})
            self.api_files.update({env: f"{DEVICE_FILES_MOUNT}/{name}" for env, name in DEVICE_FILES_OPTIONAL.items()
                                   if (self.device_files / name).is_file()})

    def name(self, role: str, previous: bool = False) -> str:
        return f"{self.instance}-{role}" + ("-previous" if previous else "")

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def presenter_key(self) -> Path:
        return self.root / "secrets" / "presenter.key"

    @property
    def loopback_bind(self) -> bool:
        return self.bind_host in LOOPBACK_HOSTS

    @property
    def gateway_url(self) -> str:
        """#587: where the deploy checks and status reach the gateway: its bind address (IPv6 in brackets; a wildcard
        bind through the loopback of its family), so an IPv6-only gateway is checked where it listens."""
        host = self.bind_host
        with contextlib.suppress(ValueError):  # "localhost" stays a name
            address = ipaddress.ip_address(host)
            if address.is_unspecified:
                host = "::1" if address.version == 6 else "127.0.0.1"
        return f"http://[{host}]:{self.web_port}" if ":" in host else f"http://{host}:{self.web_port}"

    def presenter_enabled(self) -> bool:
        """ADR-005 option A: the presenter path exists only when a private key file exists. #487: and only on a
        loopback gateway. Presenter capability is the ability to log in to the device over SSH and forward its port;
        a non-loopback bind would hand it to the network without ADR-005's still-open TLS / mTLS control, so a
        deployment with a key and such a bind is refused instead of silently dropping or exposing presenter access."""
        key = self.presenter_key
        if not key.exists():
            return False
        if stat.S_IMODE(key.stat().st_mode) & 0o077:
            raise DeployError(f"{key} must not be readable by group/others (chmod 600)")
        if not self.loopback_bind:
            raise DeployError(f"presenter access requires a loopback gateway, but bind_host is {self.bind_host}: "
                              "ADR-005 keeps presenter access off any network until its TLS / mTLS control exists "
                              "(remove the presenter key or bind 127.0.0.1)")
        return True


def read_state(settings: Settings, which: str) -> dict | None:
    path = settings.state_dir / f"{which}.json"
    return json.loads(path.read_text()) if path.exists() else None


def write_state(settings: Settings, which: str, value: dict) -> None:
    commit_state(settings, {which: value})


def _write_private(path: Path, data: bytes) -> None:
    """Write a file only the deploying user can read (#170: the Fury's umask 002 left the state files 664) and flush it
    to disk."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def commit_state(settings: Settings, changes: dict[str, dict | None]) -> None:
    """Record deployments as one step (#591): {"current" or "previous": its record, or None to remove the file}.
    Every new file, and a copy of every file it replaces, is written and flushed first, where a full disk or a
    permission error shows; then the files are swapped in by rename (no space needed) and the folder is flushed. A
    failure puts back every file already swapped and raises, so a failed commit leaves the files as they were."""
    folder = private_dir(settings.state_dir)
    paths = {which: folder / f"{which}.json" for which in changes}
    new = {which: path.with_name(path.name + ".new") for which, path in paths.items()}
    undo = {which: path.with_name(path.name + ".undo") for which, path in paths.items()}
    swapped: list[str] = []
    unrestored: list[str] = []
    try:
        for which, value in changes.items():
            if paths[which].exists():
                _write_private(undo[which], paths[which].read_bytes())
            else:
                undo[which].unlink(missing_ok=True)  # left by an interrupted commit: this file did not exist
            if value is not None:
                _write_private(new[which], (json.dumps(value, indent=2) + "\n").encode())
        with signals_deferred():  # a cancel cannot stop the swap halfway
            for which, value in changes.items():
                if value is None:
                    paths[which].unlink(missing_ok=True)
                else:
                    os.replace(new[which], paths[which])
                swapped.append(which)
            dir_fd = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            except OSError as exc:
                if exc.errno not in (errno.EINVAL, errno.ENOTSUP):  # a file system that cannot flush a folder
                    raise
            finally:
                os.close(dir_fd)
    except BaseException as exc:
        for which in reversed(swapped):
            try:
                if undo[which].exists():
                    os.replace(undo[which], paths[which])
                else:
                    paths[which].unlink(missing_ok=True)
            except OSError:
                unrestored.append(which)
        if unrestored and isinstance(exc, Exception):
            names = ", ".join(f"{which}.json (its former content is {undo[which].name})" for which in unrestored)
            raise DeployError(f"could not record the deployment in {folder}, nor put back {names}") from exc
        raise
    finally:
        for which in changes:
            for leftover in (new[which], *(() if which in unrestored else (undo[which],))):
                with contextlib.suppress(OSError):
                    leftover.unlink(missing_ok=True)


def same_deployment(a: dict | None, b: dict) -> bool:
    """Whether two deployment records run the same release, images and mode."""
    keys = ("release_tag", "mode", "model_id", "api_image", "web_image")
    return a is not None and all(a.get(k) == b.get(k) for k in keys)


def inspect_image(ref: str) -> dict:
    info = json.loads(docker("image", "inspect", ref).stdout)[0]
    return {"ref": ref, "image_id": info["Id"], "repo_digests": info.get("RepoDigests") or [],
            "architecture": info.get("Architecture"), "os": info.get("Os"),
            "revision_label": (info.get("Config", {}).get("Labels") or {}).get("org.opencontainers.image.revision")}


def zrt_preflight(settings: Settings, model_id: str | None, evidence: dict) -> None:
    """Read-only ZRT check; the record is stored first so a failure keeps it in the evidence."""
    record = {"contacted": False, "base_url": settings.zrt_base_url, "model_id": model_id,
              "endpoint_status": None, "model_listed": False}
    evidence["zrt"] = record
    if not model_id:
        raise DeployError("local mode requires a model ID (AWARE_CARE_MODEL_ID); refusing to start")
    record["contacted"] = True
    status, body = http_status(f"{settings.zrt_base_url}/models", timeout=10)
    record["endpoint_status"] = status
    # #300: anything but {"data": [{"id": ...}, ...]} is a reported failure, not a traceback.
    data = body.get("data") if isinstance(body, dict) else None
    well_formed = isinstance(data, list)
    served = [m.get("id") for m in data if isinstance(m, dict)] if status == 200 and well_formed else []
    record["served_model_ids"] = served
    # #528: the same model under ZRT's default name (the repository id), with any revision or the hf: scheme, is the
    # configured model; the API then talks to ZRT with the ID it serves. Another revision is only a note.
    qualified = model_ids.manifest_ref(_read_manifest(settings, model_id), model_id)
    match = model_ids.find_served(served, model_id, qualified)
    record["model_listed"] = match is not None
    if match is not None:
        record["served_as"] = match.served_id
        record["served_revision"] = match.revision
        note = model_ids.revision_note(match.revision, model_ids.split_ref(qualified)[1] if qualified else None) \
            if match.revision else None
        if note:
            record["revision_note"] = note
            log(f"note: {note}")
    if status != 200:
        raise DeployError(f"ZRT endpoint {settings.zrt_base_url}/models answered {status}; local mode unavailable")
    if not well_formed:
        record["malformed_reply"] = True
        raise DeployError(f"ZRT endpoint {settings.zrt_base_url}/models answered 200 without a model list; "
                          "local mode unavailable")
    if match is None:
        raise DeployError(f"configured model {model_id} is not served by ZRT (it serves: {', '.join(served) or 'none'}); "
                          "local mode unavailable")


def _read_manifest(settings: Settings, model_id: str | None = None) -> dict:
    """The model manifest the API will use, read from this checkout (the image keeps the repository layout); #537:
    the catalogue entry's when the configured manifest describes another model, as the API selects it."""
    path = settings.api_files.get("AWARECARE_MODEL_MANIFEST") or "/srv/aware-care/infra/model-manifest.json"
    local = REPO_ROOT / path.removeprefix("/srv/aware-care/") if path.startswith("/srv/aware-care/") else Path(path)
    if settings.device_files and path.startswith(f"{DEVICE_FILES_MOUNT}/"):  # #549: the host side of the mount
        local = settings.device_files / path.removeprefix(f"{DEVICE_FILES_MOUNT}/")
    return model_ids.selected_manifest(local, REPO_ROOT / "infra/models/catalog.json", model_id, REPO_ROOT)


def start_containers(settings: Settings, target: dict) -> None:
    data_dir = settings.root / "data" / target["mode"]
    harden_data_root(settings, target["mode"])
    labels = ["--label", f"aware-care.environment={settings.environment}",
              "--label", f"aware-care.release={target['release_tag']}",
              "--label", f"aware-care.commit={target['app_commit']}",
              "--label", f"aware-care.mode={target['mode']}"]
    hardening = ["--network", "host", "--read-only", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--restart", "unless-stopped", "--pids-limit", "512"]
    presenter = settings.presenter_enabled()
    # #487: one origin for both roles (the presenter API is a path of the same gateway).
    origins = settings.origin
    key_mount = ["-v", f"{settings.presenter_key}:/run/secrets/presenter.key:ro"] if presenter else []
    device_mount = ["-v", f"{settings.device_files}:{DEVICE_FILES_MOUNT}:ro"] if settings.device_files else []
    api_env = ["-e", f"AWARECARE_MODE={target['mode']}",
               "-e", f"AWARECARE_ALLOWED_ORIGINS={origins}",
               "-e", f"AWARECARE_APP_COMMIT={target['app_commit']}",
               "-e", f"AWARECARE_DATA_DIR={CONTAINER_DATA_DIR}",
               "-e", f"AWARECARE_MODEL_BASE_URL={settings.zrt_base_url}",
               "-e", "AWARECARE_ALLOW_CLOUD_FALLBACK=false"]
    if target["mode"] == "local":
        api_env += ["-e", f"AWARECARE_MODEL_ID={target['model_id']}"]
    for name, path in settings.api_files.items():
        api_env += ["-e", f"{name}={path}"]
    if presenter:
        api_env += ["-e", "AWARECARE_PRESENTER_KEY_FILE=/run/secrets/presenter.key"]
    secrets_file = settings.root / "secrets" / "api.env"
    if secrets_file.exists():
        mode = stat.S_IMODE(secrets_file.stat().st_mode)
        if mode & 0o077:
            raise DeployError(f"{secrets_file} must not be readable by group/others (chmod 600)")
        api_env += ["--env-file", str(secrets_file)]
    docker("run", "-d", "--name", settings.name("api"), *hardening, *labels,
           "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
           "--user", f"{os.getuid()}:{os.getgid()}",
           "-v", f"{data_dir}:{CONTAINER_DATA_DIR}:rw", *key_mount, *device_mount,
           *api_env, target["api_image"],
           "--host", "127.0.0.1", "--port", str(settings.api_port))
    web_bind = f"[{settings.bind_host}]" if ":" in settings.bind_host else settings.bind_host  # nginx IPv6 syntax
    web_env = ["-e", f"AWARECARE_WEB_BIND={web_bind}",
               "-e", f"AWARECARE_WEB_PORT={settings.web_port}", "-e", f"AWARECARE_API_PORT={settings.api_port}",
               "-e", f"AWARECARE_DEVICE_NAME={settings.device_name}",
               "-e", f"AWARECARE_DEVICE_SHORT_NAME={settings.device_short_name}",
               # #461/#487: the device script names the one configured address, so a refused address can say which
               # one to open. Older web images ignore these variables (and serve no presenter port without theirs).
               "-e", f"AWARECARE_ORIGIN={settings.origin}",
               "-e", f"AWARECARE_PRESENTER_ENABLED={1 if presenter else 0}"]
    # Runs as the deploying user so it can read the mode-600 presenter key; nginx writes only to /tmp.
    docker("run", "-d", "--name", settings.name("web"), *hardening, *labels,
           "--tmpfs", "/tmp:rw,nosuid,size=16m",
           "--user", f"{os.getuid()}:{os.getgid()}", *key_mount, *web_env,
           target["web_image"])


def wait_ready(settings: Settings) -> dict:
    deadline = time.monotonic() + settings.readiness_timeout
    url = f"{settings.gateway_url}{settings.readiness_path}"
    attempts, status, body = 0, None, None
    started = time.monotonic()
    while time.monotonic() < deadline:
        attempts += 1
        status, body = http_status(url)
        if status == 200 and isinstance(body, dict) and body.get("readiness") == "ready":
            break
        for role in ("api", "web"):
            state = container_state(settings.name(role))
            if state and not state["running"]:
                return {"url": url, "result": "FAILED", "status": status, "attempts": attempts,
                        "failure": f"{role} container exited with code {state['exit_code']}"}
        time.sleep(1)
    readiness = body.get("readiness") if isinstance(body, dict) else None
    ok = status == 200 and readiness == "ready"
    return {"url": url, "result": "PASSED" if ok else "FAILED", "status": status, "readiness": readiness,
            "attempts": attempts, "seconds": round(time.monotonic() - started, 1),
            "failure": None if ok else f"readiness {readiness or status} after {settings.readiness_timeout}s"}


def verify(settings: Settings, mode: str, guidance_timeout: float) -> tuple[bool, dict, dict | None]:
    readiness = wait_ready(settings)
    if readiness["result"] != "PASSED":
        return False, readiness, None
    flow = flow_check.run(settings.gateway_url, settings.origin, mode,
                          guidance_timeout=guidance_timeout, request_timeout=15.0,
                          total_timeout=guidance_timeout + FLOW_CHECK_OVERHEAD_SECONDS)
    support = presenter_support(settings) if flow["result"] == "PASSED" and settings.presenter_enabled() else None
    if support == "disabled":
        flow["result"] = "FAILED"
        flow["failure"] = "presenter key exists but the web container reports the presenter path disabled"
        flow["presenter_check"] = {"result": "FAILED"}
    elif support == "not_supported":
        # Releases before the presenter path (#487; for example a rollback target with the former second port, which
        # this tool no longer opens) have no presenter access here.
        flow["presenter_check"] = {"result": "NOT_SUPPORTED_BY_RELEASE"}
    elif support == "enabled":
        capabilities = api_capabilities(settings)
        flow["presenter_check"] = flow_check.presenter_check(
            settings.gateway_url, settings.origin, mode,
            scenario_handoff="scenario-handoff" in capabilities, local_scenarios="local-scenarios" in capabilities,
            quick_demos="quick-demos" in capabilities, quick_flows="quick-flows" in capabilities,
            total_timeout=PRESENTER_CHECK_SECONDS)
        if flow["presenter_check"]["result"] != "PASSED":
            flow["result"] = "FAILED"
            flow["failure"] = "presenter check: " + str(flow["presenter_check"]["failure"])
    else:
        flow["presenter_check"] = {"result": "NOT_ENABLED" if flow["result"] == "PASSED" else "NOT_RUN"}
    return flow["result"] == "PASSED", readiness, flow


def api_capabilities(settings: Settings) -> set[str]:
    """Capabilities declared by the running API image (label io.aware-care.capabilities); older images declare none."""
    info = docker("container", "inspect", settings.name("api"), check=False)
    if info.returncode != 0:
        return set()
    labels = json.loads(info.stdout)[0]["Config"].get("Labels") or {}
    return {c.strip() for c in labels.get("io.aware-care.capabilities", "").split(",") if c.strip()}


def presenter_support(settings: Settings) -> str:
    """What the running web image reports about its presenter path (25-aware-care-presenter.sh). #487: releases from
    before the path report a "presenter gateway" (a second port this tool no longer configures): not supported."""
    logs = docker("logs", settings.name("web"), check=False)
    text = (logs.stdout or "") + (logs.stderr or "")
    if "presenter path enabled" in text:
        return "enabled"
    if "presenter path disabled" in text:
        return "disabled"
    return "not_supported"


def presenter_status(settings: Settings) -> str:
    """Key presence plus what the running web container reports (a key alone does not start a listener)."""
    if not settings.presenter_key.exists():
        return "disabled (no key)"
    if not (container_state(settings.name("web")) or {}).get("running"):
        return "key present; web container not running"
    return {"enabled": "enabled at /presenter-api/", "disabled": "key present but the presenter path is disabled (check configuration)",
            "not_supported": "key present; the running release has no presenter path"}[presenter_support(settings)]


def new_progress() -> dict:
    """What the switch has done so far, so a failure at any point restores exactly that (#294).
    touched: roles whose running container this deployment stopped or tried to stop (it may still sit under its own
    name, or already be renamed to *-previous); starting: new containers may exist under the plain names."""
    return {"parking": False, "touched": [], "starting": False}


def park_current(settings: Settings, progress: dict | None = None) -> bool:
    """Stop the running deployment and keep its containers as *-previous for rollback."""
    progress = progress if progress is not None else new_progress()
    progress["parking"] = True
    parked = False
    for role in ("api", "web"):
        remove_container(settings.name(role, previous=True))
        if container_state(settings.name(role)):
            progress["touched"].append(role)
            docker("stop", "-t", "20", settings.name(role), timeout=60)
            docker("rename", settings.name(role), settings.name(role, previous=True))
            parked = True
    return parked


def restore_parked(settings: Settings, progress: dict | None = None) -> None:
    """Put back whatever was parked. New containers (if any were started) are removed first; an old container that
    was stopped but not yet renamed is simply started again; a role never reached is left alone."""
    progress = progress if progress is not None else {"touched": ["api", "web"], "starting": True}
    if progress.get("starting"):
        for role in ("api", "web"):
            remove_container(settings.name(role))
    for role in ("api", "web"):
        if role not in progress["touched"]:
            continue
        if container_state(settings.name(role, previous=True)):
            remove_container(settings.name(role))
            docker("rename", settings.name(role, previous=True), settings.name(role))
        state = container_state(settings.name(role))
        if state and not state["running"]:
            docker("start", settings.name(role))


def host_record() -> dict:
    version = docker("version", "--format", "{{.Server.Version}}", check=False)
    return {"arch": platform.machine(), "kernel": platform.release(),
            "docker_server": version.stdout.strip() if version.returncode == 0 else None,
            "runner_name": os.environ.get("RUNNER_NAME")}


def workflow_record() -> dict | None:
    if not os.environ.get("GITHUB_RUN_ID"):
        return None
    server, repo, run = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return {"run_id": run, "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "run_url": f"{server}/{repo}/actions/runs/{run}", "actor": os.environ.get("GITHUB_ACTOR"),
            "ref": os.environ.get("GITHUB_REF"), "sha": os.environ.get("GITHUB_SHA")}


def install_power_sampler(settings: Settings) -> dict:
    """W06 (ADR-017): copy this release's read-only GPU power sampler next to the runtime data. A user crontab line
    (installed once, see the runbook) keeps it running; the deploy never edits the crontab. Never fails a deploy."""
    source = Path(__file__).resolve().parents[1] / "telemetry" / "power_sampler.py"
    target = settings.root / "telemetry" / "power_sampler.py"
    try:
        private_dir(target.parent)
        target.write_text(source.read_text())
        listed = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False).stdout
        return {"installed": str(target), "cron_keeper": "power_sampler.py" in listed}
    except OSError as exc:
        return {"installed": None, "error": type(exc).__name__}


def install_boot_check(settings: Settings) -> dict:
    """#170: copy this release's post-boot check next to the runtime data. A user crontab `@reboot` line (installed
    once, see runbook §8) runs it after every boot; the deploy never edits the crontab. Never fails a deploy."""
    source = Path(__file__).resolve().parent / "boot_check.py"
    target = settings.root / "ops" / "boot_check.py"
    try:
        private_dir(target.parent)
        target.write_text(source.read_text())
        listed = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False).stdout
        return {"installed": str(target),
                "cron_at_reboot": any(line.startswith("@reboot") and "boot_check.py" in line
                                      for line in listed.splitlines())}
    except OSError as exc:
        return {"installed": None, "error": type(exc).__name__}


def deploy(settings: Settings, target: dict, *, pull: bool, require_digest: bool, guidance_timeout: float,
           evidence_out: Path | None, action: str = "deploy") -> int:
    evidence = {"schema": EVIDENCE_SCHEMA, "action": action, "environment": settings.environment,
                "device": settings.device_name,
                "instance": settings.instance, "release_tag": target["release_tag"],
                "app_commit": target["app_commit"], "mode": target["mode"],
                "model_id": target.get("model_id"), "started_at": now(), "finished_at": None,
                "outcome": "FAILED", "failure": None, "host": host_record(), "workflow": workflow_record(),
                "ports": {"api": settings.api_port, "web": settings.web_port, "origin": settings.origin},
                "zrt_base_url": settings.zrt_base_url, "zrt_base_url_source": settings.zrt_base_url_source,
                "images": {}, "preflight": {}, "zrt": {"contacted": False}, "readiness": None,
                "flow_check": None, "rollback": None, "previous_deployment": None, "presenter": None,
                "note": ("Deployment evidence for one environment. It is not requirement verification: "
                         "requirement statuses and NOT_EXECUTED acceptance records are unchanged.")}
    progress = new_progress()
    exit_code = 1
    try:
        with deploy_lock(settings.root), contextlib.ExitStack() as model_held:
            try:
                evidence["previous_deployment"] = read_state(settings, "current")
                rollback_target = read_state(settings, "previous")
                # Preflight: nothing on the device changes until every check passes. #487 first: a presenter key with a
                # non-loopback gateway is refused before anything is pulled or stopped (ADR-005).
                presenter = settings.presenter_enabled()
                if ARCH_ALIASES.get(platform.machine(), platform.machine()) != settings.expected_arch:
                    raise DeployError(f"host architecture {platform.machine()} is not {settings.expected_arch}")
                if shutil.which("docker") is None:
                    raise DeployError("docker is not installed for the deploying user")
                for role in ("api", "web"):
                    ref = target[f"{role}_image"]
                    if require_digest and "@sha256:" not in ref:
                        raise DeployError(f"{role} image must be pinned by digest")
                    if pull:
                        log(f"pulling {ref}")
                        docker("pull", "--quiet", ref, timeout=PULL_TIMEOUT_SECONDS)
                    image = inspect_image(ref)
                    evidence["images"][role] = image
                    if ARCH_ALIASES.get(image["architecture"], image["architecture"]) != settings.expected_arch:
                        raise DeployError(f"{role} image architecture {image['architecture']} does not match the host")
                    # #297: the image must have been built from the release commit (build_images.sh sets the label).
                    if image.get("revision_label") != target["app_commit"]:
                        raise DeployError(f"{role} image revision label {image.get('revision_label')!r} is not the "
                                          f"release commit {target['app_commit']}")
                # #487: the presenter API is a path of the one gateway (no port of its own).
                evidence["presenter"] = {"enabled": presenter, "path": "/presenter-api/" if presenter else None,
                                         "origin": settings.origin if presenter else None, "bind": settings.bind_host}
                if settings.legacy_presenter:
                    evidence["presenter"]["ignored_legacy_settings"] = settings.legacy_presenter
                    log(f"ignoring {', '.join(settings.legacy_presenter)}: since #487 the presenter API is the path "
                        "/presenter-api/ of the one gateway port")
                ours = {p for role, p in (("api", settings.api_port), ("web", settings.web_port))
                        if (container_state(settings.name(role)) or {}).get("running")}
                ports = [settings.api_port, settings.web_port]
                foreign = [p for p in ports if p not in ours and port_in_use(p)]
                evidence["preflight"]["ports_held_by_other_processes"] = foreign
                if foreign:
                    raise DeployError(f"loopback port(s) {foreign} are in use by another process")
                if target["mode"] == "local":
                    zrt_preflight(settings, target.get("model_id"), evidence)
                else:
                    evidence["zrt"] = {"contacted": False, "reason": "mock mode never contacts ZRT"}
                evidence["preflight"]["result"] = "PASSED"
                # #578: the checks call the device model in local mode (and so may a rollback to a local release):
                # take its lock before anything changes, and hold it until the checks and any rollback are done.
                if "local" in (target["mode"], (evidence["previous_deployment"] or {}).get("mode")):
                    model_held.enter_context(model_lock(f"nano_deploy.py {action} {target['release_tag']} (checks)"))
                    evidence["model_lock"] = "held"

                log("switching containers")
                park_current(settings, progress)
                progress["starting"] = True
                start_containers(settings, target)
                ok, evidence["readiness"], evidence["flow_check"] = verify(settings, target["mode"], guidance_timeout)
                if ok:
                    # #300: a rollback (the command, or a deploy of the recorded rollback target) must not make the
                    # release it rolled back from the next rollback target. The target is cleared instead; the evidence
                    # names the release that was replaced.
                    is_rollback = action == "rollback" or same_deployment(rollback_target, target)
                    rolled_back_from = is_rollback and not same_deployment(evidence["previous_deployment"], target)
                    changes: dict[str, dict | None] = {}
                    if rolled_back_from:
                        changes["previous"] = None
                    # #170: redeploying what already runs keeps the recorded rollback target, instead of replacing it
                    # with the same deployment (which left nothing different to roll back to).
                    elif (evidence["previous_deployment"]
                          and not same_deployment(evidence["previous_deployment"], target)):
                        changes["previous"] = evidence["previous_deployment"]
                    changes["current"] = {
                        "release_tag": target["release_tag"], "app_commit": target["app_commit"],
                        "mode": target["mode"], "model_id": target.get("model_id"),
                        "api_image": target["api_image"], "web_image": target["web_image"],
                        "deployed_at": now(), "instance": settings.instance}
                    # #591: recording the deployment is part of the commit. The parked containers and the rollback
                    # guard stay until both state files are written; a full disk or a refused write restores the old
                    # release, which the unchanged files still name.
                    try:
                        commit_state(settings, changes)
                    except OSError as exc:
                        raise DeployError(f"could not record the deployment in {settings.state_dir} "
                                          f"({errno.errorcode.get(exc.errno, 'error')}: {exc.strerror or exc}); "
                                          "it is not kept") from exc
                    if rolled_back_from:
                        evidence["rolled_back_from"] = evidence["previous_deployment"]
                    # Committed: the new deployment passed its checks and is recorded, so a later error must not
                    # remove it.
                    progress["parking"] = False
                    for role in ("api", "web"):
                        remove_container(settings.name(role, previous=True))
                    evidence["outcome"] = "SUCCEEDED"
                    evidence["power_sampler"] = install_power_sampler(settings)
                    evidence["boot_check"] = install_boot_check(settings)
                    exit_code = 0
                else:
                    evidence["failure"] = ((evidence["flow_check"] or {}).get("failure")
                                           or evidence["readiness"].get("failure"))
                    evidence["rollback"] = automatic_rollback(settings, progress, guidance_timeout)
                    evidence["outcome"] = evidence["rollback"]["outcome"]
            except DeployError as exc:
                evidence["failure"] = str(exc)
                if progress["parking"] and evidence["rollback"] is None:
                    evidence["rollback"] = automatic_rollback(settings, progress, guidance_timeout)
                    evidence["outcome"] = evidence["rollback"]["outcome"]
            except BaseException as exc:
                # #294: a cancel (SIGINT/SIGTERM), a crash in a check or any other error once parking has started
                # restores whatever was parked, then re-raises. A signal leaves only seconds before SIGKILL, so the
                # restored deployment is not re-checked then. Only the exception type is recorded, never content.
                interrupted = isinstance(exc, (KeyboardInterrupt, DeployInterrupted))
                if isinstance(exc, DeployInterrupted):
                    evidence["failure"] = str(exc)
                elif isinstance(exc, KeyboardInterrupt):
                    evidence["failure"] = "interrupted by signal SIGINT"
                else:
                    evidence["failure"] = f"unexpected error: {type(exc).__name__}"
                if progress["parking"] and evidence["rollback"] is None:
                    evidence["rollback"] = automatic_rollback(settings, progress, guidance_timeout,
                                                              verify_restored=not interrupted)
                    evidence["outcome"] = evidence["rollback"]["outcome"]
                raise
    except DeployError as exc:  # the device lock was not obtained; nothing changed
        evidence["failure"] = str(exc)
    finally:
        evidence["finished_at"] = now()
        write_evidence(settings, evidence, evidence_out)
    log(f"outcome: {evidence['outcome']}" + (f" ({evidence['failure']})" if evidence["failure"] else ""))
    return exit_code


def automatic_rollback(settings: Settings, progress: dict, guidance_timeout: float,
                       verify_restored: bool = True) -> dict:
    """Restore whatever the switch parked (#294). The failed attempt is still reported as failed. Never raises:
    a failure while restoring is reported as ROLLBACK_FAILED."""
    try:
        with signals_deferred():
            for role in ("api", "web"):
                state = container_state(settings.name(role))
                if progress["starting"] and state and not state["running"]:
                    log(f"{role} container exited with code {state['exit_code']}; "
                        f"see `docker logs {settings.name(role)}`")
            previous = read_state(settings, "current")
            if not progress["touched"]:
                if progress["starting"]:
                    for role in ("api", "web"):
                        remove_container(settings.name(role))
                return {"outcome": "FAILED", "detail": "no previous deployment to restore; nothing is left running"}
            log("restoring the previous deployment")
            restore_parked(settings, progress)
    except Exception as exc:  # noqa: BLE001  (reported, never a traceback that skips the evidence)
        detail = str(exc) if isinstance(exc, DeployError) else f"unexpected error: {type(exc).__name__}"
        return {"outcome": "ROLLBACK_FAILED", "detail": detail}
    if not verify_restored:
        return {"outcome": "RESTORED_UNCHECKED", "restored": previous,
                "detail": "interrupted: the parked containers were restarted without readiness or flow checks; "
                          "run `nano_deploy.py status`"}
    mode = (previous or {}).get("mode", "mock")
    try:
        ok, readiness, flow = verify(settings, mode, guidance_timeout)
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "ROLLBACK_FAILED", "restored": previous, "detail": f"check error: {type(exc).__name__}"}
    return {"outcome": "ROLLED_BACK" if ok else "ROLLBACK_FAILED", "restored": previous,
            "readiness": readiness, "flow_check": flow}


def write_evidence(settings: Settings, evidence: dict, evidence_out: Path | None) -> None:
    text = json.dumps(evidence, indent=2) + "\n"
    try:
        folder = settings.root / "evidence"
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = evidence["started_at"].replace(":", "").replace("+0000", "Z")
        (folder / f"{stamp}-{evidence['release_tag']}-{evidence['action']}.json").write_text(text)
    except OSError as exc:
        log(f"could not write device evidence copy: {exc}")
    if evidence_out:
        evidence_out.parent.mkdir(parents=True, exist_ok=True)
        evidence_out.write_text(text)
    print(text)


def status(settings: Settings) -> int:
    report = {"instance": settings.instance, "data_root": str(settings.root),
              "current": read_state(settings, "current"), "previous": read_state(settings, "previous"),
              "containers": {role: container_state(settings.name(role)) for role in ("api", "web")},
              "presenter_gateway": presenter_status(settings), "bind_host": settings.bind_host,
              "model_base_url": model_base_url(settings.name("api"))}
    code, body = http_status(f"{settings.gateway_url}{settings.readiness_path}")
    report["readiness"] = {"status": code, "readiness": (body or {}).get("readiness") if isinstance(body, dict) else None}
    print(json.dumps(report, indent=2))
    return 0


def create_presenter_key(settings: Settings, rotate: bool) -> int:
    key = settings.presenter_key
    if key.exists() and not rotate:
        print(f"[nano-deploy] presenter key already exists at {key} (use --rotate to replace it)")
        return 0
    harden_data_root(settings)
    private_dir(key.parent)
    tmp = key.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(secrets.token_hex(32) + "\n")
    tmp.replace(key)
    print(f"[nano-deploy] presenter key {'rotated' if rotate else 'created'} at {key} (mode 600; value not shown). "
          "Redeploy to enable or refresh the presenter path /presenter-api/.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent / "demo-zgx-nano.json")
    parser.add_argument("--data-root", help="Device directory for data, state and evidence (default from config)")
    parser.add_argument("--instance", help="Container name prefix (default from config)")
    parser.add_argument("--api-port", type=int)
    parser.add_argument("--web-port", type=int)
    parser.add_argument("--origin", help="Browser origin the API accepts (default from config)")
    parser.add_argument("--device-name", help="#537: the device name shown by the gateway (default from config)")
    parser.add_argument("--device-short-name", help="#537: its short form (default from config)")
    parser.add_argument("--device-files", help="#537: a directory with device-inventory.json and telemetry-pricing.json "
                        "for the API, mounted read-only")
    parser.add_argument("--zrt-base-url", help="ZRT's OpenAI-compatible base URL, replacing the config's zrt.base_url; "
                        "loopback only, like it (#535)")
    parser.add_argument("--bind-host", help="Gateway bind address (default from config, 127.0.0.1); presenter access "
                        "requires loopback (#487)")
    # #487: obsolete (one port and one origin for both roles); accepted so older commands still parse, then ignored.
    parser.add_argument("--presenter-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--presenter-origin", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    dep = sub.add_parser("deploy", help="Deploy a release in an explicit mode")
    dep.add_argument("--mode", required=True, choices=["mock", "local"])
    dep.add_argument("--release-tag", required=True)
    dep.add_argument("--app-commit", required=True)
    dep.add_argument("--api-image", required=True)
    dep.add_argument("--web-image", required=True)
    dep.add_argument("--model-id", help="Required in local mode; must be listed by ZRT")
    dep.add_argument("--no-pull", action="store_true", help="Use local images (CI package smoke test only)")
    dep.add_argument("--allow-unpinned", action="store_true", help="Accept tag references (CI package smoke test only)")
    dep.add_argument("--expected-arch", help="Override the configured platform architecture (CI smoke test only)")
    dep.add_argument("--guidance-timeout", type=float, default=90.0)
    dep.add_argument("--evidence-out", type=Path)

    rb = sub.add_parser("rollback", help="Redeploy state/previous.json")
    rb.add_argument("--guidance-timeout", type=float, default=90.0)
    rb.add_argument("--evidence-out", type=Path)
    rb.add_argument("--no-pull", action="store_true", help="Use local images (CI package smoke test only)")
    rb.add_argument("--allow-unpinned", action="store_true", help="Accept tag references (CI package smoke test only)")

    sub.add_parser("status", help="Show recorded deployments, containers and readiness")
    pk = sub.add_parser("presenter-key", help="Create (or --rotate) the presenter key")
    pk.add_argument("--rotate", action="store_true")
    args = parser.parse_args()

    try:
        settings = Settings(load_config(args.config), args)
    except (OSError, ValueError, KeyError, DeployError) as exc:
        print(f"[nano-deploy] configuration error: {exc}", file=sys.stderr)
        return 2
    if args.command == "status":
        return status(settings)
    if args.command == "presenter-key":
        return create_presenter_key(settings, args.rotate)
    if args.command == "rollback":
        target = read_state(settings, "previous")
        if not target:
            print("[nano-deploy] no previous deployment is recorded (a rollback clears it, #300)", file=sys.stderr)
            return 1
        action = "rollback"
    else:
        if args.mode == "local" and not args.model_id:
            print("[nano-deploy] local mode requires --model-id", file=sys.stderr)
            return 2
        target = {"release_tag": args.release_tag, "app_commit": args.app_commit, "mode": args.mode,
                  "model_id": args.model_id if args.mode == "local" else None,
                  "api_image": args.api_image, "web_image": args.web_image}
        action = "deploy"
    # #294: a workflow cancel or timeout sends SIGINT and then SIGTERM; both restore what was parked.
    signal.signal(signal.SIGTERM, _raise_interrupted)
    try:
        return deploy(settings, target, pull=not args.no_pull, require_digest=not args.allow_unpinned,
                      guidance_timeout=args.guidance_timeout, evidence_out=args.evidence_out, action=action)
    except (KeyboardInterrupt, DeployInterrupted) as exc:
        print(f"[nano-deploy] {exc or 'interrupted'}; see the evidence for what was restored", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 143


if __name__ == "__main__":
    sys.exit(main())
