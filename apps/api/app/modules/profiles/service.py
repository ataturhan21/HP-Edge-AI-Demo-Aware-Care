"""M02 profiles (R04-R06).

Saving a profile requires saved mode, which needs an approved local identity
layer (ADR-005, open). Guests therefore have no stored profile: getProfile
returns {"profile": null} and A02 keeps session-only facts in browser memory,
sending them as user-origin confirmed_context when the case is created.
"""
from __future__ import annotations

from typing import Any

from app.core.errors import ApiError
from app.core.security import SessionInfo


def get_profile(ctx, session: SessionInfo) -> dict[str, Any]:
    return {"profile": None}


def save_profile(ctx, session: SessionInfo) -> dict[str, Any]:
    raise ApiError(403, "SAVED_MODE_REQUIRED",
                   "Saving a profile needs a saved account. Use your details for this session instead.")
