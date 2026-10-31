"""Validate browser requests and LLM output before writing routing decisions."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    document_ids: list[StrictInt] = Field(min_length=1, max_length=1000)
    batch_id: StrictInt | None = None
    revisions: dict[str, StrictStr]
    allow_unapproved: StrictBool = False


class RouteMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    destination_id: int = Field(gt=0)
    rule_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=10000)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class RoutingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    routes: list[RouteMatch] = Field(max_length=1000)
