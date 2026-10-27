"""M04 request model mirroring spec/contracts/AnswerWrite.schema.json."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, Strict, StrictInt, StrictStr, model_validator

from app.modules.cases.schemas import Revision


class DurationValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # #261: no NaN or Infinity. #463: a JSON number only (an integer is a number; "2" and true are refused).
    amount: Annotated[float, Strict(), Field(ge=0, allow_inf_nan=False)]
    unit: Literal["hours", "days", "weeks", "months", "years"]


# Strict scalars: JSON booleans/floats must not be coerced into integers or strings (the contract has no boolean).
AnswerValue = (Annotated[StrictStr, Field(max_length=2000)] | StrictInt
               | Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=100)]], Field(max_length=50)]
               | DurationValue | None)


class AnswerWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Revision
    status: Literal["answered", "unknown", "skipped"]
    value: AnswerValue

    @model_validator(mode="after")
    def null_iff_unanswered(self) -> "AnswerWrite":
        if (self.status == "answered") == (self.value is None):
            raise ValueError("value must be null exactly when status is unknown or skipped")
        return self
