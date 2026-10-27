"""Synthetic fixture pack loader (fixtures/*.json). Scenarios, scripted records and the mock adapter are mock-only;
local mode uses only the fictional provider directory (ADR-004).

Fixtures are UI simulation seeds, not clinical approval. Every file must declare
data_mode=synthetic and clinical_execution_enabled=false or loading fails.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FIXTURE_FILES = ("scenarios.json", "questions.json", "providers.json", "profiles.json", "id-map.json")


class FixtureError(RuntimeError):
    pass


@dataclass(frozen=True)
class FixturePack:
    scenarios: dict[str, dict[str, Any]]
    questions: dict[str, dict[str, Any]]
    providers: list[dict[str, Any]]
    provider_source: dict[str, Any]
    directory_version: str
    profiles: dict[str, dict[str, Any]]
    id_map: dict[str, str]
    fixture_version: str
    # sha256 of a bundled synthetic record file -> its scripted sample (fixtures/records/, ADR-009).
    record_samples: dict[str, dict[str, Any]] = field(default_factory=dict)


def _load_record_samples(directory: Path, profiles_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Key scripted samples by the actual bytes on disk, never by the manifest's claimed hash."""
    manifest_path = directory / "records" / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("data_mode") != "synthetic" or manifest.get("clinical_execution_enabled") is not False:
        raise FixtureError("record sample manifest is not a disabled synthetic pack")
    scripted = {s["fixture_id"]: s for s in profiles_doc.get("record_samples", [])}
    samples: dict[str, dict[str, Any]] = {}
    for entry in manifest["samples"]:
        if entry["fixture_id"] not in scripted:
            continue  # e.g. the unreadable sample: it must be rejected by validation, never extracted
        data = (directory / "records" / entry["file"]).read_bytes()
        samples[hashlib.sha256(data).hexdigest()] = scripted[entry["fixture_id"]]
    return samples


def load_fixture_pack(directory: Path) -> FixturePack:
    docs: dict[str, Any] = {}
    for name in FIXTURE_FILES:
        try:
            docs[name] = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FixtureError(f"fixture {name} unreadable") from exc
    for name in ("scenarios.json", "questions.json", "providers.json", "profiles.json"):
        doc = docs[name]
        if doc.get("data_mode") != "synthetic" or doc.get("clinical_execution_enabled") is not False:
            raise FixtureError(f"fixture {name} is not a disabled synthetic pack")
    providers = docs["providers.json"]
    return FixturePack(
        scenarios={s["id"]: s for s in docs["scenarios.json"]["scenarios"]},
        questions={q["template_id"]: q for q in docs["questions.json"]["questions"]},
        providers=providers["providers"],
        provider_source=providers["source_records"][0],
        directory_version=providers["snapshot_version"],
        profiles={p["fixture_id"]: p for p in docs["profiles.json"]["profiles"]},
        id_map=docs["id-map.json"]["mappings"],
        fixture_version=docs["scenarios.json"]["fixture_version"],
        record_samples=_load_record_samples(directory, docs["profiles.json"]),
    )
