"""Server-only configuration loader for the infra/.env.example contract.

Owner M12 (R26, R34, R37, R38). Values never reach the browser bundle. Invalid
mode/provider/fallback values fail startup instead of silently degrading.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]


class ConfigError(RuntimeError):
    pass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name)
    try:
        value = default if raw in (None, "") else int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return value


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def loopback_base_url(raw: str) -> str:
    """ADR-014: the model endpoint must be ZRT on this device's loopback. Parsed, not prefix-matched (#150):
    `http://127.0.0.1:8080@remote.example/v1` starts with the loopback prefix but connects to remote.example."""
    url = raw.strip().rstrip("/")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ConfigError("AWARECARE_MODEL_BASE_URL must be a loopback ZRT endpoint") from exc
    host = parts.hostname or ""
    bracketed = f"[{host}]" if ":" in host else host
    if (parts.scheme != "http" or host not in LOOPBACK_HOSTS or port is None or parts.username is not None
            or parts.password is not None or parts.netloc != f"{bracketed}:{port}" or parts.query or parts.fragment):
        raise ConfigError("AWARECARE_MODEL_BASE_URL must be a loopback ZRT endpoint (http://127.0.0.1:<port>/…, "
                          "no user info)")
    return url


def _path(name: str, default: str) -> Path:
    raw = os.environ.get(name) or default
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class Settings:
    mode: str
    model_provider: str
    model_base_url: str
    model_id: str | None
    model_manifest: Path
    device_inventory: Path
    retrieval_mode: str
    active_generation_limit: int
    queued_generation_limit: int
    queue_retry_after_seconds: int
    generation_deadline_seconds: int
    # #153 (ADR-003 amendment 3): the red-flag screen of the concern when a case is created or its concern edited.
    # A screen that does not answer in time defers to the screen before guidance, which still fails closed.
    concern_screen_timeout_seconds: int
    schema_repair_limit: int
    allowed_origins: tuple[str, ...]
    cookie_secure: bool
    data_dir: Path
    fixtures_dir: Path = field(default=REPO_ROOT / "fixtures")
    # Reviewed pathway packages (ADR-003): content/pathways/registry.json names the enabled package.
    pathways_dir: Path = field(default=REPO_ROOT / "content" / "pathways")
    # W06 telemetry (ADR-017): reviewed list prices and assumptions for the cost estimates. Per device since ADR-018
    # (AWARECARE_TELEMETRY_PRICING; the ZGX Fury's copy is infra/fury/telemetry-pricing.json).
    telemetry_pricing: Path = field(default=REPO_ROOT / "infra" / "telemetry-pricing.json")
    # ADR-005 option A: HMAC key shared with the presenter gateway. None disables presenter access.
    presenter_key: bytes | None = None
    # Peers allowed to present a gateway assertion (the gateways run on host loopback).
    presenter_trusted_peers: tuple[str, ...] = ("127.0.0.1", "::1")
    # #537: the model catalogue; its entry for the configured model supplies the manifest when model_manifest
    # describes another model (a machine other than the Nano or the Fury serves a catalogue model).
    model_catalog: Path = field(default=REPO_ROOT / "infra" / "models" / "catalog.json")

    def manifest(self) -> dict:
        """The model manifest for the configured model (model_ids.selected_manifest); {} when unreadable."""
        from app.runtime.model_ids import selected_manifest
        return selected_manifest(self.model_manifest, self.model_catalog, self.model_id, REPO_ROOT)


def _presenter_key() -> bytes | None:
    """Read the presenter gateway key named by AWARECARE_PRESENTER_KEY_FILE (server-only, never logged)."""
    raw = os.environ.get("AWARECARE_PRESENTER_KEY_FILE")
    if not raw:
        return None
    try:
        key = Path(raw).read_text().strip().encode()
    except OSError as exc:
        raise ConfigError("AWARECARE_PRESENTER_KEY_FILE is set but cannot be read") from exc
    if len(key) < 32:
        raise ConfigError("the presenter key must be at least 32 characters")
    return key


def load_settings() -> Settings:
    mode = os.environ.get("AWARECARE_MODE", "mock")
    if mode not in {"mock", "local"}:
        raise ConfigError("AWARECARE_MODE must be mock or local")
    provider = os.environ.get("AWARECARE_MODEL_PROVIDER", "zrt")
    if provider != "zrt":
        raise ConfigError("AWARECARE_MODEL_PROVIDER must be zrt")
    if _bool("AWARECARE_ALLOW_CLOUD_FALLBACK", False):
        raise ConfigError("AWARECARE_ALLOW_CLOUD_FALLBACK must be false")
    retrieval = os.environ.get("AWARECARE_RETRIEVAL_MODE", "offline")
    if retrieval != "offline":
        raise ConfigError("AWARECARE_RETRIEVAL_MODE supports only offline in this build")
    base_url = loopback_base_url(os.environ.get("AWARECARE_MODEL_BASE_URL", "http://127.0.0.1:8080/v1"))
    origins = tuple(o.strip() for o in os.environ.get(
        "AWARECARE_ALLOWED_ORIGINS", "http://127.0.0.1:15173").split(",") if o.strip())
    if not origins or "*" in origins:
        raise ConfigError("AWARECARE_ALLOWED_ORIGINS must list exact origins")
    return Settings(
        mode=mode,
        model_provider=provider,
        model_base_url=base_url,
        model_id=os.environ.get("AWARECARE_MODEL_ID") or None,
        model_manifest=_path("AWARECARE_MODEL_MANIFEST", "infra/model-manifest.json"),
        device_inventory=_path("AWARECARE_DEVICE_INVENTORY", "infra/device-inventory.json"),
        telemetry_pricing=_path("AWARECARE_TELEMETRY_PRICING", "infra/telemetry-pricing.json"),
        model_catalog=_path("AWARECARE_MODEL_CATALOG", "infra/models/catalog.json"),
        retrieval_mode=retrieval,
        active_generation_limit=_int("AWARECARE_ACTIVE_GENERATION_LIMIT", 1, 1),
        queued_generation_limit=_int("AWARECARE_QUEUED_GENERATION_LIMIT", 3, 0),
        queue_retry_after_seconds=_int("AWARECARE_QUEUE_RETRY_AFTER_SECONDS", 5, 1),
        generation_deadline_seconds=_int("AWARECARE_GENERATION_DEADLINE_SECONDS", 60, 1),
        concern_screen_timeout_seconds=_int("AWARECARE_CONCERN_SCREEN_TIMEOUT_SECONDS", 20, 1),
        schema_repair_limit=_int("AWARECARE_SCHEMA_REPAIR_LIMIT", 1, 0),
        allowed_origins=origins,
        # Development-only exception: plain HTTP over the loopback SSH tunnel.
        # Trusted-network TLS deployments must set this to true.
        cookie_secure=_bool("AWARECARE_COOKIE_SECURE", False),
        data_dir=_path("AWARECARE_DATA_DIR", "runtime-data/api"),
        presenter_key=_presenter_key(),
    )
