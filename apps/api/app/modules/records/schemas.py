"""M06 request models mirroring spec/contracts/FactReview.schema.json and FactCorrection.schema.json."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.cases.schemas import Revision

# #261: NaN and Infinity are refused with 422 (they are not JSON and would break every later read of the fact).
CorrectionValue = (Annotated[str, Field(max_length=2000)] | Annotated[float, Field(allow_inf_nan=False)] | bool
                   | None
                   | Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=50)])


class FactCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: CorrectionValue
    units: Annotated[str, Field(max_length=100)] | None


class FactReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Revision
    action: Literal["confirm", "reject", "correct"]
    corrected_value: FactCorrection | None = None

    @model_validator(mode="after")
    def correction_iff_correct(self) -> "FactReview":
        if (self.action == "correct") != ("corrected_value" in self.model_fields_set):
            raise ValueError("corrected_value is required exactly when action is correct")
        return self
