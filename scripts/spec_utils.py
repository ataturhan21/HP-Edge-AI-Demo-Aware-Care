"""Stdlib-only helpers for the specification checks: safe repository reads, the schema file set and JSON Schema
formats. The .yaml registries deliberately use the JSON-compatible subset of YAML, so no YAML parser is needed.
(The spec hash lock, spec/lock.json, was retired with the lean delivery rules, ADR-019.)
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

class SpecError(ValueError):
    """Readable integrity failure without a traceback."""


def safe_path(root: Path, value: str, *, must_exist: bool = False) -> Path:
    """Require an exact relative POSIX path, including through symlinks."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SpecError(f"Invalid repository-relative path: {value!r}")
    relative = PurePosixPath(value)
    if (relative.is_absolute() or ".." in relative.parts
            or str(relative) != value or ":" in value or value == "."):
        raise SpecError(f"Absolute, non-canonical or traversing path is forbidden: {value!r}")
    path = root / value
    if not path.resolve().is_relative_to(root.resolve()):
        raise SpecError(f"Path escapes the repository through a symlink: {value}")
    if must_exist and not path.is_file():
        raise SpecError(f"Required file does not exist: {value}")
    return path


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SpecError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def read_json(root: Path, relative: str) -> Any:
    path = safe_path(root, relative, must_exist=True)
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecError(f"Cannot read {relative} as JSON-compatible data: {exc}") from exc


# One definition of "the schema files" for check_contracts.py and check_traceability.py (#301).
# Recursive, so a schema placed in a subfolder also fails the registry checks.
SCHEMA_GLOB = "*.schema.json"


def schema_files(root: Path) -> list[Path]:
    return sorted((root / "spec/contracts").rglob(SCHEMA_GLOB))


# --- JSON Schema formats (#301) -------------------------------------------------------------------------------
# jsonschema's FormatChecker checks "date-time" only with rfc3339-validator and "uri" only with rfc3987 installed;
# without them (CI runs `uv run --no-project --with jsonschema==4.25.1`) both pass anything. These explicit checkers
# need nothing beyond the standard library. Non-strings pass, as the JSON Schema format rules require.

_DATE_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[Zz]|[+-](\d{2}):(\d{2}))")
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:(?:[A-Za-z0-9\-._~!$&'()*+,;=:@/?\[\]]|%[0-9A-Fa-f]{2})*"
                  r"(?:#(?:[A-Za-z0-9\-._~!$&'()*+,;=:@/?]|%[0-9A-Fa-f]{2})*)?")


def is_date_time(value: Any) -> bool:
    """RFC 3339 date-time: full date, time, seconds (60 allowed for a leap second), and an offset."""
    if not isinstance(value, str):
        return True
    match = _DATE_TIME.fullmatch(value)
    if not match:
        return False
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    try:
        date(year, month, day)
    except ValueError:
        return False
    offset_ok = match.group(7) is None or (int(match.group(7)) <= 23 and int(match.group(8)) <= 59)
    return hour <= 23 and minute <= 59 and second <= 60 and offset_ok


def is_uri(value: Any) -> bool:
    """RFC 3986 URI: a scheme, then only URI characters or percent-encodings, at most one fragment."""
    return not isinstance(value, str) or bool(_URI.fullmatch(value))


def format_checker():
    """A jsonschema FormatChecker that really checks date-time and uri (needs jsonschema itself)."""
    from jsonschema import FormatChecker
    checker = FormatChecker()
    checker.checks("date-time")(is_date_time)
    checker.checks("uri")(is_uri)
    return checker
