"""This machine's NVIDIA hardware and the catalogue model that suits it (#537).

demo.sh runs it as a script (see `main`); the tests run it against stand-ins. Standard library only. It reads:

- the product name from DMI (/sys/class/dmi/id/product_name, readable without root);
- the GPUs from `nvidia-smi --query-gpu=...` (name, memory, compute capability, driver) and the CUDA version from the
  `nvidia-smi` banner. A GB10 reports its memory as "[N/A]" because it is unified: its usable memory is MemTotal from
  /proc/meminfo. Any other GPU's usable memory is its own; several GPUs add up (tensor parallel across them);
- the CUDA toolkit with bin/nvcc, in the serve scripts' order (AWARECARE_CUDA_HOME, the highest /usr/local/cuda-<v>,
  /usr/local/cuda);
- the architecture (uname -m).

AWARECARE_HW_ROOT (tests only) is a directory standing in for / : proc/meminfo, sys/class/dmi/id/product_name and an
optional `arch` file are read under it. AWARECARE_CUDA_ROOT stands in for /usr/local, as for the serve scripts.

The catalogue (infra/models/catalog.json) lists the models largest first; `choose` takes the first entry whose
`hardware` holds this machine's class and whose minimum usable memory and GPU count it meets.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG = REPO_ROOT / "infra" / "models" / "catalog.json"
SMI_FIELDS = "index,name,memory.total,compute_cap,driver_version"
# DMI placeholders that name no product (firmware defaults).
_DMI_JUNK = re.compile(r"^(to be filled.*|system product name|default string|none|not specified|o\.e\.m\.?|"
                       r"unknown|0+|x+)$", re.IGNORECASE)
_SHORT_DROP = {"workstation", "desktop", "pc", "tower", "ai", "station", "computer", "system"}
_NAME_FALLBACK = ("NVIDIA GPU workstation", "GPU workstation")
UNIFIED_FRACTION = 0.40   # a candidate model on unified memory: the Nano's share, leaving the rest to the system
# A "24 GB" card reports 24,564 MiB (23.99 GiB), a "16 GB" one 16,376 MiB: tiers allow 5 % below their minimum.
TOLERANCE = 0.95


@dataclass
class Gpu:
    index: int
    name: str
    memory_mib: int | None        # None: "[N/A]" (unified memory)
    compute_cap: str | None = None


@dataclass
class Hardware:
    product_name: str             # raw DMI, "" when unreadable
    device_name: str              # safe for the gateway: [A-Za-z0-9 .-]{1,40}
    short_name: str
    architecture: str             # uname -m
    platform: str                 # docker platform: linux/arm64 or linux/amd64
    gpus: list[Gpu] = field(default_factory=list)
    driver: str | None = None
    cuda_version: str | None = None      # what the driver supports (nvidia-smi banner)
    toolkit: str | None = None           # a CUDA toolkit directory with bin/nvcc
    toolkit_version: str | None = None
    mem_total_gib: float | None = None   # /proc/meminfo
    hardware_class: str = "none"         # gb10, gb300, grace, discrete or none
    unified: bool = False
    usable_gib: float = 0.0

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)

    def gpu_summary(self) -> str:
        if not self.gpus:
            return "none found"
        names = sorted({g.name for g in self.gpus})
        lead = f"{self.gpu_count}x " if self.gpu_count > 1 else ""
        mem = ("unified memory" if self.unified and self.gpus[0].memory_mib is None
               else f"{_gb(self.gpus[0].memory_mib)} GB" + (" each" if self.gpu_count > 1 else ""))
        return f"{lead}{' / '.join(names)}, {mem}"


def _gb(mib: int | None) -> str:
    return "?" if mib is None else f"{mib / 1024:.1f}"


def _root() -> Path | None:
    raw = os.environ.get("AWARECARE_HW_ROOT")
    return Path(raw) if raw else None


def _read(path: str, root: Path | None) -> str:
    target = root / path.lstrip("/") if root else Path(path)
    try:
        return target.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _run(args: list[str]) -> str | None:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def safe_names(product: str) -> tuple[str, str]:
    """(device name, short name) for the gateway and the page: plain characters, at most 40 (and 24) long."""
    text = re.sub(r"[^A-Za-z0-9 .-]+", " ", product or "")
    text = re.sub(r"\s+", " ", text).strip(" .-")
    if not text or _DMI_JUNK.match(text):
        return _NAME_FALLBACK
    name = text
    while len(name) > 40:
        name = name.rsplit(" ", 1)[0] if " " in name else name[:40]
    words = name.split(" ")
    if words[0].upper() == "HP" and len(words) > 1:
        words = words[1:]
    while len(words) > 1 and words[-1].lower() in _SHORT_DROP:
        words.pop()
    short = " ".join(words)
    while len(short) > 24 and " " in short:
        short = short.rsplit(" ", 1)[0]
    return name, short[:24].strip() or name[:24]


def parse_gpus(text: str) -> tuple[list[Gpu], str | None]:
    """GPUs from `nvidia-smi --query-gpu=index,name,memory.total,compute_cap,driver_version --format=csv,noheader,
    nounits`. A line with fewer fields (an older driver, or a bare name) still names the GPU."""
    gpus: list[Gpu] = []
    driver = None
    for i, line in enumerate(l for l in text.splitlines() if l.strip()):
        cells = [c.strip() for c in line.split(",")]
        if len(cells) >= 3 and cells[0].isdigit():
            index, name, mem = int(cells[0]), cells[1], cells[2]
            cap = cells[3] if len(cells) > 3 and re.fullmatch(r"\d+\.\d+", cells[3]) else None
            driver = cells[4] if len(cells) > 4 and cells[4] and "N/A" not in cells[4] else driver
        else:
            index, name, mem, cap = i, cells[0], "", None
        digits = re.match(r"(\d+)", mem.replace(" ", ""))
        gpus.append(Gpu(index, name, int(digits[1]) if digits else None, cap))
    return gpus, driver


def query_gpus(smi: str = "nvidia-smi") -> tuple[list[Gpu], str | None, str | None]:
    """(GPUs, driver version, CUDA version) from nvidia-smi; no GPU when it is missing or fails."""
    out = _run([smi, f"--query-gpu={SMI_FIELDS}", "--format=csv,noheader,nounits"])
    if out is None:  # an older driver without compute_cap
        out = _run([smi, "--query-gpu=index,name,memory.total,driver_version", "--format=csv,noheader,nounits"])
        if out is not None:
            out = "\n".join(",".join(c[:3] + ["", *c[3:]]) for c in (l.split(",") for l in out.splitlines() if l))
    gpus, driver = parse_gpus(out or "")
    banner = _run([smi]) if gpus else None
    cuda = re.search(r"CUDA Version:\s*([0-9.]+)", banner or "")
    return gpus, driver, cuda[1] if cuda else None


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", path.name)) or (0,)


def find_toolkit() -> tuple[str | None, str | None]:
    """(directory, version) of the CUDA toolkit the serve scripts would choose; (None, None) when none has nvcc."""
    home = os.environ.get("AWARECARE_CUDA_HOME")
    root = Path(os.environ.get("AWARECARE_CUDA_ROOT") or "/usr/local")
    candidates = [Path(home)] if home else []
    try:
        versioned = sorted((p for p in root.glob("cuda-*") if p.is_dir()), key=_version_key, reverse=True)
    except OSError:
        versioned = []
    candidates += versioned + [root / "cuda"]
    for d in candidates:
        if os.access(d / "bin" / "nvcc", os.X_OK):
            version = None
            try:
                version = json.loads((d / "version.json").read_text())["cuda"]["version"]
            except (OSError, ValueError, KeyError, TypeError):
                found = re.search(r"cuda-([0-9.]+)$", str(d.resolve()) if d.is_symlink() else d.name)
                version = found[1] if found else None
            return str(d), version
    return None, None


def mem_total_gib(root: Path | None) -> float | None:
    found = re.search(r"^MemTotal:\s*(\d+)\s*kB", _read("/proc/meminfo", root), re.MULTILINE)
    return round(int(found[1]) / 1024 / 1024, 1) if found else None


def classify(gpus: list[Gpu]) -> tuple[str, bool]:
    """(hardware class, unified memory)."""
    if not gpus:
        return "none", False
    names = " ".join(g.name for g in gpus).upper()
    if re.search(r"\bGB10\b", names):
        return "gb10", True
    if "GB300" in names:
        return "gb300", True
    if "GB200" in names:
        return "grace", True
    return "discrete", False


def detect(smi: str = "nvidia-smi") -> Hardware:
    root = _root()
    product = _read("/sys/class/dmi/id/product_name", root)
    name, short = safe_names(product)
    arch = _read("/arch", root) if root and (root / "arch").is_file() else platform.machine()
    gpus, driver, cuda = query_gpus(smi)
    toolkit, toolkit_version = find_toolkit()
    total = mem_total_gib(root)
    klass, unified = classify(gpus)
    if klass == "gb10":
        usable = total or 0.0
    else:
        usable = round(sum(g.memory_mib or 0 for g in gpus) / 1024, 1)
    docker_arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(arch, arch)
    return Hardware(product, name, short, arch, f"linux/{docker_arch}", gpus, driver, cuda, toolkit, toolkit_version,
                    total, klass, unified, usable)


# ------------------------------------------------------------------ the catalogue


def load_catalog(path: Path = CATALOG) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_entry(catalog: dict[str, Any], label: str) -> dict[str, Any] | None:
    """The entry for a label or repository id (any case, with or without hf: and @revision)."""
    from app.runtime.model_ids import aliases  # noqa: PLC0415 (the script path adds apps/api to sys.path)
    wanted = aliases(label)
    for entry in catalog.get("models", []):
        if wanted & aliases(entry["label"], entry["repository_id"]):
            return entry
    return None


@dataclass
class Choice:
    entry: dict[str, Any] | None
    profile: str = ""            # nano, fury or generic
    status: str = ""             # qualified or candidate
    tensor_parallel: int = 1
    settings: dict[str, Any] = field(default_factory=dict)
    reason: str = ""             # why, or why nothing
    qualified_on: str = ""       # "HP ZGX Nano, 2026-10-15" when qualified elsewhere
    gpu_devices: list[int] = field(default_factory=list)  # #549: zrt service start --gpu-devices (several GPUs)

    @property
    def label(self) -> str:
        return self.entry["label"] if self.entry else ""


def _power_of_two_at_most(n: int) -> int:
    p = 1
    while p * 2 <= n:
        p *= 2
    return p


def ranked_gpus(hw: Hardware) -> list[Gpu]:
    """The GPUs, largest memory first (then by index): tensor parallel takes the first ones."""
    return sorted(hw.gpus, key=lambda g: (-(g.memory_mib or 0), g.index))


def tensor_parallel(hw: Hardware, entry: dict[str, Any]) -> int:
    """How many GPUs the entry runs on here: on several discrete or Grace GPUs a power of two up to the entry's
    max_tensor_parallel (a divisor of its KV heads), else one."""
    if hw.hardware_class in ("discrete", "grace") and hw.gpu_count > 1:
        return _power_of_two_at_most(min(hw.gpu_count, entry.get("max_tensor_parallel", 1)))
    return 1


def capacity(hw: Hardware, entry: dict[str, Any]) -> float:
    """#549: the memory the entry can use here. On several discrete or Grace GPUs only that of the GPUs it runs on
    (four 16 GB cards hold a 64 GB tier only if the model may spread over all four), else the usable memory."""
    if hw.hardware_class not in ("discrete", "grace") or hw.gpu_count <= 1:
        return hw.usable_gib
    return round(sum(g.memory_mib or 0 for g in ranked_gpus(hw)[:tensor_parallel(hw, entry)]) / 1024, 1)


def choose(hw: Hardware, catalog: dict[str, Any], label: str | None = None, device: str | None = None) -> Choice:
    """The entry to serve here: --device nano|fury forces that device's qualified model and settings; --model a
    catalogue label; otherwise the first entry this hardware's class and memory allow."""
    models = catalog.get("models", [])
    if device in ("nano", "fury"):
        for entry in models:
            for klass, variant in entry["serving"].items():
                if variant.get("device") == device:
                    return _finish(Choice(entry, device, "qualified", 1, variant, f"--device {device}"), entry, klass)
    if label:
        entry = find_entry(catalog, label)
        if entry is None:
            known = ", ".join(e["label"] for e in models)
            return Choice(None, reason=f"--model {label} is not in the catalogue (known: {known})")
        why = f"--model {label}"
        if capacity(hw, entry) < entry["min_memory_gb"] * TOLERANCE:
            why += f"; note: it wants {entry['min_memory_gb']} GB, this machine has {capacity(hw, entry):g} GB for it"
    else:
        if hw.hardware_class == "none":
            return Choice(None, reason="no NVIDIA GPU found (nvidia-smi lists none)")
        entry = next((e for e in models if hw.hardware_class in e["hardware"]
                      and capacity(hw, e) >= e["min_memory_gb"] * TOLERANCE and hw.gpu_count >= e.get("min_gpus", 1)),
                     None)
        if entry is None:
            least = min((e["min_memory_gb"] for e in models), default=0)
            return Choice(None, reason=f"{hw.usable_gib:g} GB of GPU memory is less than the smallest model needs "
                                       f"({least} GB)")
        why = f"{hw.usable_gib:g} GB usable on {hw.hardware_class}: tier {entry['tier']}"
        if capacity(hw, entry) != hw.usable_gib:
            why += f" ({capacity(hw, entry):g} GB on the {tensor_parallel(hw, entry)} GPUs it runs on)"
    klass = hw.hardware_class if hw.hardware_class in entry["serving"] else "default"
    variant = entry["serving"].get(klass)
    if variant is None:
        only = ", ".join(entry["hardware"])
        return Choice(None, reason=f"{entry['label']} is served only on {only} hardware (this is {hw.hardware_class})")
    profile = variant.get("device", "generic")
    tp = tensor_parallel(hw, entry) if profile == "generic" else 1
    # #549: on several GPUs ZRT is told which ones (--gpu-devices); it sets vLLM's tensor parallel size from them
    gpus = [g.index for g in ranked_gpus(hw)[:tp]] if profile == "generic" and hw.gpu_count > 1 else []
    settings = dict(variant)
    if profile == "generic" and hw.unified and klass == "default":
        settings["gpu_memory_fraction"] = min(settings.get("gpu_memory_fraction", 1.0), UNIFIED_FRACTION)
    status = entry.get("status_by_hardware", {}).get(hw.hardware_class, {}).get("status", "candidate") \
        if profile == "generic" or klass == hw.hardware_class else "candidate"
    return _finish(Choice(entry, profile, status, tp, settings, why, gpu_devices=gpus), entry, klass)


def _finish(choice: Choice, entry: dict[str, Any], klass: str) -> Choice:
    quals = [f"{q['device']}, {q['date']}" for q in entry.get("status_by_hardware", {}).values()
             if q.get("status") == "qualified"]
    choice.qualified_on = "; ".join(quals)
    return choice


def serve_args(choice: Choice) -> list[str]:
    """The `zrt service start` flags after the model and label, one per element (the generic serve script)."""
    s = choice.settings
    args = [f"--gpu-memory-fraction={s['gpu_memory_fraction']:g}" if "gpu_memory_fraction" in s else None,
            f"--extra=--max-model-len={s['max_model_len']}" if "max_model_len" in s else None,
            f"--extra=--max-num-seqs={s['max_num_seqs']}" if "max_num_seqs" in s else None,
            # #549: `zrt service start --gpu-devices 0,1` sets --tensor-parallel-size itself (zrt service start --help)
            f"--gpu-devices={','.join(map(str, choice.gpu_devices))}" if choice.gpu_devices else None]
    args += [f"--extra={flag}" for flag in s.get("extra", [])]
    if s.get("speculative_config"):
        args.append(f"--extra=--speculative-config={s['speculative_config']}")
    return [a for a in args if a]


def settings_line(choice: Choice) -> str:
    s = choice.settings
    gpus = ",".join(map(str, choice.gpu_devices))
    parts = [f"tensor parallel {choice.tensor_parallel} (GPUs {gpus})" if choice.tensor_parallel > 1
             else f"one GPU (GPU {gpus})" if gpus else "one GPU",
             f"gpu-memory-fraction {s.get('gpu_memory_fraction', '-')}", f"max-model-len {s.get('max_model_len', '-')}",
             f"max-num-seqs {s.get('max_num_seqs', '-')}"]
    if s.get("speculative_config"):
        parts.append("MTP speculative decoding")
    return ", ".join(parts)


# ------------------------------------------------------------------ the generic device profile's files


def inventory(hw: Hardware, today: str | None = None, choice: Choice | None = None) -> dict[str, Any]:
    """infra/device-inventory.json's shape, filled from this machine (detected, not reviewed); #549: with the served
    model's status on this hardware."""
    day = today or _dt.date.today().isoformat()
    gpu = hw.gpus[0].name if hw.gpus else "none"
    model = {"label": choice.label, "status_on_this_hardware": choice.status or "candidate",
             "qualified_on": choice.qualified_on or None, "serving": settings_line(choice)} if choice and choice.entry \
        else None
    return {
        "schema_version": "1.0",
        "inventory_id": f"detected-{re.sub(r'[^a-z0-9]+', '-', hw.device_name.lower()).strip('-')}-{day}"[:100],
        "status": "detected_by_demo_sh",
        "observed_on": day,
        "evidence": "Detected by ./demo.sh (apps/api/app/runtime/hardware.py) when it deployed; not reviewed (#537)",
        "device": {
            "product_name": hw.device_name,
            "product_detail": hw.product_name or "DMI product name not readable",
            "device_count": 1,
            "architecture": hw.architecture,
            "gpu_name": f"{hw.gpu_count}x {gpu}" if hw.gpu_count > 1 else gpu,
            "gpu_count": hw.gpu_count,
            "gpu_compute_capability": hw.gpus[0].compute_cap if hw.gpus else None,
            "gpu_memory_total": ", ".join(f"{g.memory_mib:,} MiB" if g.memory_mib else "unified" for g in hw.gpus)
            or None,
            "memory_architecture": "unified (GPU and system share memory)" if hw.unified else "discrete GPU memory",
            "usable_memory_gib": hw.usable_gib,
            "system_memory_total": f"{hw.mem_total_gib:g} GiB" if hw.mem_total_gib else None,
            "nvidia_driver_version": hw.driver,
            "nvidia_smi_cuda_version": hw.cuda_version,
            "installed_cuda_toolkit_version": f"{hw.toolkit_version or '?'} at {hw.toolkit}" if hw.toolkit else None,
        },
        "model": model,
    }


def candidate_manifest(choice: Choice, hw: Hardware, base: dict[str, Any]) -> dict[str, Any]:
    """#549: the model manifest for a model that is a candidate on this hardware. `base` is the catalogue entry's
    manifest (for Qwen3.6 the Nano's, with its 2026-10-15 qualification): the API would show that qualification and its
    ZRT versions as if they held here. This one keeps the model's identity and says what is true here: a candidate,
    not qualified (no re-qualification, no runtime), and where it was qualified."""
    entry = choice.entry or {}
    model = dict(base.get("model") or {"repository_id": entry.get("repository_id"),
                                       "served_model_id": entry.get("label"), "revision": entry.get("revision")})
    if choice.settings.get("max_model_len"):
        model["context_limit_tokens"] = choice.settings["max_model_len"]
    elsewhere = f" It was qualified on other hardware: {choice.qualified_on}." if choice.qualified_on else ""
    return {
        "schema_version": "1.0",
        "manifest_id": f"{entry.get('label')}@{str(entry.get('revision', ''))[:8]}-candidate",
        "status": "candidate",
        "selected_serving_interface": "zrt",
        "model": model,
        "qualification": {
            "status": "candidate",
            "hardware": f"{hw.device_name}: {hw.gpu_summary()}",
            "qualified_on_other_hardware": choice.qualified_on or None,
            "note": (f"Candidate on this hardware ({hw.device_name}, {hw.gpu_summary()}): chosen by GPU memory and not "
                     f"qualified here under ADR-002.{elsewhere} ./demo.sh check-model runs the advisory AI regression "
                     "set (written by ./demo.sh, #549)."),
            "runtime_requalifications": [],
        },
    }


def pricing(choice_label: str, base: dict[str, Any]) -> dict[str, Any]:
    """The Nano's reviewed telemetry prices with neutral device assumptions. The like-for-like cloud reference is kept
    only for the model it prices (the Nano's); otherwise the first frontier reference is the default."""
    out = json.loads(json.dumps(base))
    out["note"] = ("Generated by ./demo.sh for a machine without its own reviewed prices (#537): the cloud references "
                   "are the Nano's reviewed ones; the device price is not known (0 until you enter it on the page) and "
                   "the other assumptions are neutral defaults. Estimates use measured tokens and energy on this "
                   "machine; nothing here is a measured saving.")
    refs = out.get("cloud_references", [])
    keep_like = choice_label == "qwen3.6-35b-a3b-fp8"
    refs = [r for r in refs if keep_like or r.get("comparison") != "like_for_like"]
    if refs and not any(r.get("default") for r in refs):
        refs[0]["default"] = True
    out["cloud_references"] = refs
    a = out.setdefault("assumptions", {})
    a["device_price_usd"] = {"value": 0, "label": "Device price not known for this machine: an estimate of $0 until "
                             "you enter its purchase price", "note": "Neutral default (#537). Editable on the page."}
    a["other_system_power_w"] = {"value": 0, "label": "Other (non-GPU) system power during AI calls: not measured "
                                 "(assumption). Enter a wall-socket meter reading minus GPU power to include it."}
    tokens = a.get("fallback_tokens_per_consultation")
    if isinstance(tokens, dict):
        tokens["label"] = ("The guidance call only, from the Nano's ADR-002 re-qualification; used only until tokens "
                           "are measured on this machine")
    return out


# ------------------------------------------------------------------ command line


def _shell(values: dict[str, Any]) -> str:
    lines = []
    for key, value in values.items():
        text = "" if value is None else str(value)
        lines.append(f"{key}={text.replace(chr(10), ' ')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Command line for demo.sh.

      detect [--json]                     this machine (key=value lines, or JSON)
      choose [--model L] [--device D]     detect, then the catalogue entry (key=value lines); exit 1 when none fits
      serve-args --model L [--tp N]       the generic serve script's flags, one per line
      device-files --model L --out DIR    write device-inventory.json and telemetry-pricing.json for this machine
    --catalog FILE replaces infra/models/catalog.json.
    """
    parser = argparse.ArgumentParser(prog="hardware.py")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--json", action="store_true")
    c = sub.add_parser("choose")
    c.add_argument("--model", default="")
    c.add_argument("--device", default="")
    s = sub.add_parser("serve-args")
    s.add_argument("--model", required=True)
    s.add_argument("--tp", type=int, default=0)
    f = sub.add_parser("device-files")
    f.add_argument("--model", required=True)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--pricing-base", type=Path, default=REPO_ROOT / "infra" / "telemetry-pricing.json")
    args = parser.parse_args(argv)

    hw = detect()
    if args.cmd == "detect":
        if args.json:
            print(json.dumps({**asdict(hw), "gpu_count": hw.gpu_count}, indent=2))
        else:
            print(_shell(_hw_values(hw)))
        return 0
    catalog = load_catalog(args.catalog)
    if args.cmd == "choose":
        choice = choose(hw, catalog, args.model or None, args.device if args.device in ("nano", "fury") else None)
        values = _hw_values(hw)
        values.update(_choice_values(choice))
        print(_shell(values))
        return 0 if choice.entry else 1
    if args.cmd == "serve-args":
        choice = choose(hw, catalog, args.model)
        if choice.entry is None:
            print(choice.reason, file=sys.stderr)
            return 1
        if args.tp:
            choice.tensor_parallel = args.tp
            if choice.gpu_devices:
                choice.gpu_devices = [g.index for g in ranked_gpus(hw)[:args.tp]]
        print("\n".join(serve_args(choice)))
        return 0
    entry = find_entry(catalog, args.model)
    label = entry["label"] if entry else args.model
    choice = choose(hw, catalog, label)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "device-inventory.json").write_text(json.dumps(inventory(hw, choice=choice), indent=2) + "\n")
    # #549: the model manifest the API reads: the catalogue's when the model is qualified on this hardware, else one
    # that says it is a candidate here (not the Nano's qualification)
    manifest_file = args.out / "model-manifest.json"
    if choice.entry is not None:
        from app.runtime.model_ids import catalog_manifest  # noqa: PLC0415 (the script path adds apps/api)
        base = catalog_manifest(catalog, choice.label, REPO_ROOT) or {}
        manifest = base if choice.status == "qualified" else candidate_manifest(choice, hw, base)
        manifest_file.write_text(json.dumps(manifest, indent=2) + "\n")
    elif manifest_file.exists():
        manifest_file.unlink()
    base = json.loads(args.pricing_base.read_text(encoding="utf-8"))
    (args.out / "telemetry-pricing.json").write_text(json.dumps(pricing(label, base), indent=2) + "\n")
    print(args.out)
    return 0


def _hw_values(hw: Hardware) -> dict[str, Any]:
    return {"HW_PRODUCT": hw.product_name, "HW_NAME": hw.device_name, "HW_SHORT": hw.short_name,
            "HW_ARCH": hw.architecture, "HW_PLATFORM": hw.platform, "HW_CLASS": hw.hardware_class,
            "HW_UNIFIED": int(hw.unified), "HW_GPU_COUNT": hw.gpu_count, "HW_GPUS": hw.gpu_summary(),
            "HW_GPU_NAME": hw.gpus[0].name if hw.gpus else "", "HW_USABLE_GB": f"{hw.usable_gib:g}",
            "HW_MEM_GB": f"{hw.mem_total_gib:g}" if hw.mem_total_gib else "", "HW_DRIVER": hw.driver or "",
            "HW_CUDA": hw.cuda_version or "", "HW_TOOLKIT": hw.toolkit or "",
            "HW_TOOLKIT_VERSION": hw.toolkit_version or ""}


def _choice_values(choice: Choice) -> dict[str, Any]:
    e = choice.entry or {}
    return {"M_LABEL": choice.label, "M_REPO": e.get("repository_id", ""), "M_REVISION": e.get("revision", ""),
            "M_HF": f"hf:{e['repository_id']}@{e['revision']}" if e else "", "M_SIZE_GB": e.get("size_gb", ""),
            "M_TIER": e.get("tier", ""), "M_PROFILE": choice.profile, "M_STATUS": choice.status,
            "M_TP": choice.tensor_parallel, "M_SETTINGS": settings_line(choice) if e else "",
            "M_QUALIFIED_ON": choice.qualified_on, "M_REASON": choice.reason,
            "M_GPUS": ",".join(map(str, choice.gpu_devices))}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # apps/api, for app.runtime.model_ids
    sys.exit(main())
