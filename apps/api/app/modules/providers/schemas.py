"""M09 request models mirroring ProviderSearchRequest / ProviderCriteria / ProviderLocationQuery."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.cases.schemas import Revision

Strict = ConfigDict(extra="forbid")


class ProviderLocationQuery(BaseModel):
    model_config = Strict
    location_id: str | None
    city: Annotated[str, Field(max_length=100)] | None
    region: Annotated[str, Field(max_length=100)] | None
    postal_code: Annotated[str, Field(max_length=20)] | None


class ProviderCriteria(BaseModel):
    model_config = Strict
    location: ProviderLocationQuery
    radius_miles: Literal[5, 10, 25, 50, 100]
    specialty_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(max_length=30)]
    exact_plan_id: Annotated[str, Field(min_length=1, max_length=100)] | None
    required_verified_plan: StrictBool
    visit_type: Literal["in_person", "telehealth", "either"]
    language: Annotated[str, Field(min_length=1, max_length=100)] | None
    required_language: StrictBool
    ranked_preferences: Annotated[list[Literal["plan", "language", "visit_type"]], Field(max_length=3)]

    @model_validator(mode="after")
    def required_needs_value(self) -> "ProviderCriteria":
        if self.required_verified_plan and not self.exact_plan_id:
            raise ValueError("required_verified_plan needs exact_plan_id")
        if self.required_language and not self.language:
            raise ValueError("required_language needs language")
        if len(set(self.ranked_preferences)) != len(self.ranked_preferences):
            raise ValueError("ranked_preferences must be unique")
        return self


class ProviderSearchRequest(BaseModel):
    model_config = Strict
    expected_revision: Revision
    criteria: ProviderCriteria
