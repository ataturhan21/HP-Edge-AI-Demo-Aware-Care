"""#537: the demo runs on any NVIDIA machine; apps/api/app/runtime/hardware.py detects it and picks a catalogue model.

nvidia-smi is a stand-in on PATH (FAKE_SMI_CSV answers the --query-gpu call, FAKE_CUDA the banner); /proc/meminfo, the
DMI product name and `uname -m` come from AWARECARE_HW_ROOT. The machines are the two ZGX devices, the HP Z8 that
started #537 (2x RTX PRO 5000 72GB Blackwell), single 24, 16 and 8 GB cards and a machine without a GPU.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "apps/api/app/runtime/hardware.py"
CATALOG = json.loads((ROOT / "infra/models/catalog.json").read_text())
sys.path.insert(0, str(ROOT / "apps/api"))
from app.runtime import hardware  # noqa: E402

SMI = """\
#!/bin/sh
case "$*" in
  *--query-gpu=*) [ -n "${FAKE_SMI_CSV:-}" ] || exit 9; printf '%s\\n' "$FAKE_SMI_CSV" ;;
  *) [ -n "${FAKE_SMI_CSV:-}" ] || exit 9; echo "| NVIDIA-SMI 580.95.05   Driver Version: 580.95.05   CUDA Version: ${FAKE_CUDA:-13.0} |" ;;
esac
"""

# name -> (nvidia-smi rows, MemTotal kB, DMI product name, uname -m)
MACHINES = {
    "gb10": ("0, NVIDIA GB10, [N/A], 12.1, 580.95.05", 125442420, "HP ZGX Nano G1n AI Station", "aarch64"),
    "gb300": ("0, NVIDIA GB300, 256703, 10.3, 595.99.02", 779000000, "HP ZGX Fury G1n AI Station", "aarch64"),
    "z8": ("0, NVIDIA RTX PRO 5000 72GB Blackwell, 73728, 12.0, 580.95.05\n"
           "1, NVIDIA RTX PRO 5000 72GB Blackwell, 73728, 12.0, 580.95.05", 263000000,
           "HP Z8 Fury G5 Workstation Desktop PC", "x86_64"),
    "24gb": ("0, NVIDIA GeForce RTX 4090, 24564, 8.9, 580.95.05", 65000000, "HP Z4 G5 Workstation", "x86_64"),
    "16gb": ("0, NVIDIA GeForce RTX 4080, 16376, 8.9, 580.95.05", 32000000, "HP Z2 Tower G9 Workstation", "x86_64"),
    "8gb": ("0, NVIDIA GeForce RTX 4060, 8188, 8.9, 580.95.05", 16000000, "To Be Filled By O.E.M.", "x86_64"),
    "none": ("", 16000000, "HP EliteDesk 800 G6", "x86_64"),
    # #549: the Z8's neighbours
    "ada48": ("0, NVIDIA RTX 6000 Ada Generation, 49140, 8.9, 580.95.05", 131000000, "HP Z8 G5 Workstation", "x86_64"),
    "h100": ("0, NVIDIA H100 80GB HBM3, 81559, 9.0, 580.95.05", 263000000, "HP ProLiant DL380a Gen11", "x86_64"),
    "l40s4": ("\n".join(f"{i}, NVIDIA L40S, 46068, 8.9, 580.95.05" for i in range(4)), 527000000,
              "HP ProLiant DL380a Gen11", "x86_64"),
    "16gb4": ("\n".join(f"{i}, NVIDIA RTX A4000, 16376, 8.6, 580.95.05" for i in range(4)), 131000000,
              "HP Z8 G4 Workstation", "x86_64"),
}

# name -> (class, usable GiB, label, profile, status, tensor parallel); None: no local model
EXPECTED = {
    "gb10": ("gb10", "119.6", "qwen3.6-35b-a3b-fp8", "nano", "qualified", "1"),
    "gb300": ("gb300", "250.7", "qwen3.8-flash-next-fp8", "fury", "qualified", "1"),
    "z8": ("discrete", "144", "qwen3.6-35b-a3b-fp8", "generic", "candidate", "2"),
    "24gb": ("discrete", "24", "qwen3-14b-fp8", "generic", "candidate", "1"),
    "16gb": ("discrete", "16", "qwen3-8b-fp8", "generic", "candidate", "1"),
    "8gb": ("discrete", "8", None, "", "", "1"),
    "none": ("none", "0", None, "", "", "1"),
    "ada48": ("discrete", "48", "qwen3-14b-fp8", "generic", "candidate", "1"),
    "h100": ("discrete", "79.6", "qwen3.6-35b-a3b-fp8", "generic", "candidate", "1"),
    "l40s4": ("discrete", "180", "qwen3.6-35b-a3b-fp8", "generic", "candidate", "2"),
    # 64 GB in all, but Qwen3.6 spreads over at most 2 of them (32 GB): the 24-63 GB tier on all four
    "16gb4": ("discrete", "64", "qwen3-14b-fp8", "generic", "candidate", "4"),
}
# #549: the GPUs ZRT is told to use (zrt service start --gpu-devices), on machines with more than one
GPU_DEVICES = {"z8": "0,1", "l40s4": "0,1", "16gb4": "0,1,2,3"}


def machine_env(tmp: Path, name: str) -> dict[str, str]:
    """An environment in which hardware.py sees the named machine."""
    rows, mem_kb, product, arch = MACHINES[name]
    root = tmp / name
    (root / "proc").mkdir(parents=True, exist_ok=True)
    (root / "proc/meminfo").write_text(f"MemTotal:       {mem_kb} kB\nMemFree:        1000 kB\n")
    (root / "sys/class/dmi/id").mkdir(parents=True, exist_ok=True)
    (root / "sys/class/dmi/id/product_name").write_text(product + "\n")
    (root / "arch").write_text(arch + "\n")
    bin_dir = tmp / "bin"
    if not bin_dir.exists():
        bin_dir.mkdir()
        (bin_dir / "nvidia-smi").write_text(SMI)
        (bin_dir / "nvidia-smi").chmod(0o755)
    cuda = tmp / "cuda"
    if not cuda.exists():
        for d in ("cuda-12.8", "cuda-13.0"):
            nvcc = cuda / d / "bin/nvcc"
            nvcc.parent.mkdir(parents=True)
            nvcc.write_text("#!/bin/sh\n")
            nvcc.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "AWARECARE_"))}
    return {**env, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AWARECARE_HW_ROOT": str(root),
            "AWARECARE_CUDA_ROOT": str(cuda), "FAKE_SMI_CSV": rows}


def values(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


class HardwareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hw-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def helper(self, name: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", str(HELPER), *args], env=machine_env(self.tmp, name),
                              capture_output=True, text=True, timeout=60)

    def test_detects_each_machine(self):
        for name in MACHINES:
            with self.subTest(machine=name):
                out = values(self.helper(name, "detect").stdout)
                klass, usable = EXPECTED[name][:2]
                self.assertEqual((out["HW_CLASS"], out["HW_USABLE_GB"]), (klass, usable), out)
        z8 = values(self.helper("z8", "detect").stdout)
        self.assertEqual(z8["HW_GPUS"], "2x NVIDIA RTX PRO 5000 72GB Blackwell, 72.0 GB each")
        self.assertEqual((z8["HW_NAME"], z8["HW_SHORT"]), ("HP Z8 Fury G5 Workstation Desktop PC", "Z8 Fury G5"))
        self.assertEqual((z8["HW_PLATFORM"], z8["HW_CUDA"], z8["HW_DRIVER"]), ("linux/amd64", "13.0", "580.95.05"))
        self.assertTrue(z8["HW_TOOLKIT"].endswith("/cuda-13.0"), z8)  # the highest version with bin/nvcc
        nano = values(self.helper("gb10", "detect").stdout)
        self.assertEqual((nano["HW_GPUS"], nano["HW_UNIFIED"], nano["HW_PLATFORM"]),
                         ("NVIDIA GB10, unified memory", "1", "linux/arm64"))
        none = values(self.helper("none", "detect").stdout)
        self.assertEqual((none["HW_GPU_COUNT"], none["HW_GPUS"]), ("0", "none found"))
        junk = values(self.helper("8gb", "detect").stdout)  # a firmware placeholder names no product
        self.assertEqual((junk["HW_NAME"], junk["HW_SHORT"]), ("NVIDIA GPU workstation", "GPU workstation"))

    def test_chooses_the_catalogue_model_for_each_machine(self):
        for name, (_, _, label, profile, status, tp) in EXPECTED.items():
            with self.subTest(machine=name):
                run = self.helper(name, "choose")
                out = values(run.stdout)
                self.assertEqual(run.returncode, 0 if label else 1, run.stdout + run.stderr)
                self.assertEqual((out["M_LABEL"] or None, out["M_PROFILE"], out["M_STATUS"], out["M_TP"]),
                                 (label, profile, status, tp))
                self.assertEqual(out["M_GPUS"], GPU_DEVICES.get(name, ""))
        self.assertIn("less than the smallest model needs (12 GB)", values(self.helper("8gb", "choose").stdout)["M_REASON"])
        self.assertIn("no NVIDIA GPU found", values(self.helper("none", "choose").stdout)["M_REASON"])
        z8 = values(self.helper("z8", "choose").stdout)
        self.assertEqual(z8["M_HF"], "hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d08a9490559dae23d0cff1d9466213d989")
        self.assertEqual(z8["M_QUALIFIED_ON"], "HP ZGX Nano, 2026-10-15")
        self.assertIn("tensor parallel 2 (GPUs 0,1), gpu-memory-fraction 0.85, max-model-len 16384", z8["M_SETTINGS"])
        small = values(self.helper("16gb4", "choose").stdout)
        self.assertIn("64 GB usable on discrete: tier 24 to 63 GB", small["M_REASON"])
        self.assertNotIn("MTP", z8["M_SETTINGS"])  # speculative decoding only where it was tested

    def test_model_and_device_options_override_the_choice(self):
        out = values(self.helper("gb10", "choose", "--model", "qwen3-14b-fp8").stdout)
        self.assertEqual((out["M_LABEL"], out["M_PROFILE"], out["M_STATUS"]), ("qwen3-14b-fp8", "generic", "candidate"))
        self.assertIn("gpu-memory-fraction 0.4,", out["M_SETTINGS"])  # unified memory: the Nano's share
        out = values(self.helper("z8", "choose", "--model", "Qwen/Qwen3-8B-FP8").stdout)
        self.assertEqual((out["M_LABEL"], out["M_TP"]), ("qwen3-8b-fp8", "2"))
        run = self.helper("z8", "choose", "--model", "qwen3.8-flash-next-fp8")
        self.assertEqual(run.returncode, 1)
        self.assertIn("served only on gb300 hardware", values(run.stdout)["M_REASON"])
        run = self.helper("z8", "choose", "--model", "llama-3")
        self.assertIn("not in the catalogue", values(run.stdout)["M_REASON"])
        out = values(self.helper("z8", "choose", "--device", "fury").stdout)
        self.assertEqual((out["M_LABEL"], out["M_PROFILE"]), ("qwen3.8-flash-next-fp8", "fury"))

    def test_serve_args_for_the_generic_serve_script(self):
        args = self.helper("z8", "serve-args", "--model", "qwen3.6-35b-a3b-fp8").stdout.splitlines()
        # #549: ZRT's own --gpu-devices sets the tensor parallel size; never both
        self.assertEqual(args[:4], ["--gpu-memory-fraction=0.85", "--extra=--max-model-len=16384",
                                    "--extra=--max-num-seqs=1", "--gpu-devices=0,1"])
        self.assertFalse(any("tensor-parallel" in a for a in args), args)
        args = self.helper("l40s4", "serve-args", "--model", "qwen3-14b-fp8", "--tp", "4").stdout.splitlines()
        self.assertIn("--gpu-devices=0,1,2,3", args)
        self.assertIn("--extra=--reasoning-parser=qwen3", args)
        self.assertIn('--extra=--default-chat-template-kwargs={"enable_thinking": false}', args)
        self.assertFalse(any("speculative" in a for a in args))
        args = self.helper("24gb", "serve-args", "--model", "qwen3-14b-fp8").stdout.splitlines()
        self.assertFalse(any("tensor-parallel" in a or "gpu-devices" in a or "language-model-only" in a for a in args), args)

    def test_device_files_describe_the_machine_with_neutral_prices(self):
        out = self.tmp / "device"
        run = self.helper("z8", "device-files", "--model", "qwen3.6-35b-a3b-fp8", "--out", str(out))
        self.assertEqual(run.returncode, 0, run.stderr)
        inv = json.loads((out / "device-inventory.json").read_text())
        self.assertEqual(inv["device"]["product_name"], "HP Z8 Fury G5 Workstation Desktop PC")
        self.assertEqual(inv["device"]["gpu_name"], "2x NVIDIA RTX PRO 5000 72GB Blackwell")
        self.assertRegex(inv["observed_on"], r"^\d{4}-\d{2}-\d{2}$")
        prices = json.loads((out / "telemetry-pricing.json").read_text())
        self.assertEqual(prices["assumptions"]["device_price_usd"]["value"], 0)
        self.assertIn("like_for_like", [r["comparison"] for r in prices["cloud_references"]])  # the Nano's model
        # #549: the API reads this manifest, so the app says "candidate on this hardware", not the Nano's qualification
        manifest = json.loads((out / "model-manifest.json").read_text())
        self.assertEqual(manifest["manifest_id"], "qwen3.6-35b-a3b-fp8@95a723d0-candidate")
        self.assertEqual((manifest["status"], manifest["qualification"]["status"]), ("candidate", "candidate"))
        self.assertEqual(manifest["qualification"]["runtime_requalifications"], [])
        self.assertNotIn("runtime", manifest)  # the Nano's ZRT and vLLM versions do not hold here
        self.assertIn("Candidate on this hardware (HP Z8 Fury G5 Workstation Desktop PC", manifest["qualification"]["note"])
        self.assertIn("qualified on other hardware: HP ZGX Nano, 2026-10-15", manifest["qualification"]["note"])
        self.assertEqual(manifest["model"]["served_model_id"], "qwen3.6-35b-a3b-fp8")
        self.assertEqual(manifest["model"]["revision"], "95a723d08a9490559dae23d0cff1d9466213d989")
        self.assertEqual(inv["model"]["status_on_this_hardware"], "candidate")
        self.assertEqual(inv["model"]["qualified_on"], "HP ZGX Nano, 2026-10-15")
        sys.path.insert(0, str(ROOT / "apps/api"))
        from app.runtime.model_ids import selected_manifest
        chosen = selected_manifest(out / "model-manifest.json", ROOT / "infra/models/catalog.json",
                                   "qwen3.6-35b-a3b-fp8", ROOT)
        self.assertEqual(chosen["manifest_id"], "qwen3.6-35b-a3b-fp8@95a723d0-candidate")
        self.helper("24gb", "device-files", "--model", "qwen3-14b-fp8", "--out", str(self.tmp / "d2"))
        self.assertEqual(json.loads((self.tmp / "d2/model-manifest.json").read_text())["status"], "candidate")
        refs = json.loads((self.tmp / "d2/telemetry-pricing.json").read_text())["cloud_references"]
        self.assertEqual({r["comparison"] for r in refs}, {"frontier"})
        self.assertEqual(sum(r["default"] for r in refs), 1)

    def test_safe_device_names(self):
        self.assertEqual(hardware.safe_names("HP ZGX Nano G1n AI Station"), ("HP ZGX Nano G1n AI Station", "ZGX Nano G1n"))
        for junk in ("", "System Product Name", "Default string", "To Be Filled By O.E.M."):
            self.assertEqual(hardware.safe_names(junk), ("NVIDIA GPU workstation", "GPU workstation"))
        name, short = hardware.safe_names('Super<script>Machine "X" (rev 2) with a really long marketing name here')
        self.assertRegex(name, r"^[A-Za-z0-9 .-]{1,40}$")
        self.assertRegex(short, r"^[A-Za-z0-9 .-]{1,24}$")


class CatalogueTest(unittest.TestCase):
    def test_entries_are_pinned_and_complete(self):
        for e in CATALOG["models"]:
            with self.subTest(model=e["label"]):
                self.assertRegex(e["revision"], r"^[0-9a-f]{40}$")
                for key in ("repository_id", "tier", "size_gb", "license", "hardware", "min_memory_gb", "min_gpus",
                            "serving", "manifest"):
                    self.assertIn(key, e)
                for variant in e["serving"].values():
                    for key in ("gpu_memory_fraction", "max_model_len", "max_num_seqs"):
                        self.assertIn(key, variant)
                manifest = e["manifest"] if isinstance(e["manifest"], dict) else \
                    json.loads((ROOT / e["manifest"]).read_text())
                self.assertEqual(manifest["model"]["served_model_id"], e["label"])
                self.assertEqual(manifest["model"]["revision"], e["revision"])
                self.assertLessEqual(len(manifest["manifest_id"]), 100)
        minimums = [e["min_memory_gb"] for e in CATALOG["models"]]
        self.assertEqual(minimums, sorted(minimums, reverse=True), "largest first")

    def test_qualified_entries_are_exactly_the_device_scripts(self):
        """The Nano and Fury keep their qualified serve scripts byte for byte; the catalogue only describes them."""
        for e in CATALOG["models"]:
            for variant in e["serving"].values():
                if "script" not in variant:
                    continue
                with self.subTest(script=variant["script"]):
                    script = (ROOT / variant["script"]).read_text()
                    self.assertIn(f"MODEL=hf:{e['repository_id']}@{e['revision']}\n", script)
                    self.assertIn(f"LABEL={e['label']}\n", script)
                    command = script[script.rindex('exec "${ZRT[@]}"'):]
                    self.assertRegex(command, rf"--gpu-memory-fraction {variant['gpu_memory_fraction']:.2f}|"
                                              rf"--gpu-memory-fraction {variant['gpu_memory_fraction']:g}\b")
                    self.assertIn(f"--max-model-len={variant['max_model_len']}", command)
                    self.assertIn(f"--max-num-seqs={variant['max_num_seqs']}", command)
                    for flag in variant["extra"]:
                        self.assertIn(flag, command)
                    self.assertIn(variant["speculative_config"], command)

    def test_the_image_contains_the_catalogue(self):
        self.assertIn("COPY infra/models/catalog.json", (ROOT / "infra/deploy/api.Dockerfile").read_text())
        self.assertIn("!infra/models/catalog.json", (ROOT / ".dockerignore").read_text())


if __name__ == "__main__":
    unittest.main()
