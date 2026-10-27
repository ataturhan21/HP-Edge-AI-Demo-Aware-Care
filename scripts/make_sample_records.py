"""Regenerate the bundled synthetic record samples in fixtures/records/ (deterministic bytes).

Usage (from repo root): cd apps/api && uv run python ../../scripts/make_sample_records.py
The sample is a fictional document for the A04 mock flow; it is not a real record and no OCR runs.
The unreadable sample is the same document truncated mid-file, to exercise malformed-file rejection.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from app.modules.exports.pdf import render  # noqa: E402

LINES = [
    ("h1", "SYNTHETIC SAMPLE RECORD - FICTIONAL PERSON"),
    ("p", "This document is part of the Aware Care demonstration fixture pack. It is not a real medical record."),
    ("h2", "Patient"),
    ("p", "Jordan Taylor (fictional)"),
    ("h2", "Medications"),
    ("p", "No medications listed in sample record"),
]


def main() -> int:
    out = ROOT / "fixtures/records"
    out.mkdir(parents=True, exist_ok=True)
    sample = render(LINES)
    (out / "synthetic-sample-record-01.pdf").write_bytes(sample)
    (out / "synthetic-unreadable-record.pdf").write_bytes(sample[: len(sample) // 2])
    manifest = {
        "data_mode": "synthetic", "clinical_execution_enabled": False, "real_file_provided": False,
        "generator": "scripts/make_sample_records.py",
        "samples": [{"fixture_id": "sample-record-01", "file": "synthetic-sample-record-01.pdf",
                     "sha256": hashlib.sha256(sample).hexdigest(), "pages": 1},
                    {"fixture_id": "unreadable-record-01", "file": "synthetic-unreadable-record.pdf",
                     "sha256": hashlib.sha256(sample[: len(sample) // 2]).hexdigest(), "expected": "rejected"}],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["samples"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
