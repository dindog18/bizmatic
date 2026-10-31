"""Strict assistant proposals cannot choose tools, connections or execution actions."""
from pydantic import BaseModel, ConfigDict, Field, JsonValue


class AssistantProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=16000)
    payload: dict[str, JsonValue] | None = None
    mappings: dict[str, dict[str, JsonValue]] | None = None
    issues: list[str] = Field(default_factory=list, max_length=100)
