"""M01 request model mirroring spec/contracts/CreateSessionRequest.schema.json."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["guest", "saved"]
    consent_version: Annotated[str, Field(min_length=1, max_length=100)]
    adult_eligible: StrictBool  # #463: JSON true/false only; "yes", 1 or "true" are refused
