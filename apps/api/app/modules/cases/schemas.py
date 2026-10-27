"""M03 request models mirroring spec/contracts (CaseWrite, CaseEdit, RevisionRequest, ReviewRequest).

Responses are validated against the canonical JSON Schemas in tests; clients can
never submit state, urgency, issued_slots or guidance IDs (extra=forbid).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt, model_validator
from pydantic_core import PydanticCustomError

Strict = ConfigDict(extra="forbid")
# #463: the contracts are strict JSON types. A revision is a JSON integer: "1", 1.0 and true are refused (422), never
# coerced. Shared by every request model with an expected or profile revision.
Revision = Annotated[StrictInt, Field(ge=1)]


def _exactly_true(value: Any) -> Any:
    if value is not True:
        raise PydanticCustomError("literal_error", "Input should be true")
    return value


# #463: an explicit confirmation ({const: true}) is the JSON value true only; 1 and 1.0 are not taken as true.
ExactlyTrue = Annotated[Literal[True], BeforeValidator(_exactly_true)]
# #261: JSON numbers only; NaN and Infinity (accepted by Python's JSON parser) are refused with 422.
Finite = Annotated[float, Field(allow_inf_nan=False)]
ContextValue = (Annotated[str, Field(max_length=2000)] | bool | int | Finite | None
                | Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=50)])


class ConfirmedContextWrite(BaseModel):
    model_config = Strict
    kind: Annotated[str, Field(min_length=1, max_length=100)]
    value: ContextValue
    units: Annotated[str, Field(max_length=100)] | None
    origin: Literal["user", "profile"]
    profile_revision: Revision | None


class CaseWrite(BaseModel):
    model_config = Strict
    # #392 (R15): may be empty only when a reviewed warning sign is ticked; the service enforces that rule.
    concern: Annotated[str, Field(max_length=4000)]
    confirmed_context: Annotated[list[ConfirmedContextWrite], Field(max_length=200)]


class CaseEdit(BaseModel):
    model_config = Strict
    expected_revision: Revision
    concern: Annotated[str, Field(min_length=1, max_length=4000)] | None = None
    confirmed_context: Annotated[list[ConfirmedContextWrite], Field(max_length=200)] | None = None

    @model_validator(mode="after")
    def one_change(self) -> "CaseEdit":
        if self.concern is None and self.confirmed_context is None:
            raise ValueError("concern or confirmed_context is required")
        return self


class RevisionRequest(BaseModel):
    model_config = Strict
    expected_revision: Revision


class ReviewRequest(BaseModel):
    model_config = Strict
    expected_revision: Revision
    facts_confirmed: ExactlyTrue
