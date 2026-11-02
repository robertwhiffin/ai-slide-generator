"""Schemas for the admin Gateway MCP connection registry."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.gateway_service_name import validate_service_name

INSTRUCTIONS_MAX_CHARS = 4000
AgentName = Literal["architect", "data_analyst"]
_FORBIDDEN_DISPLAY_CHARS = ('"', "<", ">")


def _check_display_name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 120:
        raise ValueError("display_name must be 1-120 characters")
    if any(c in value for c in _FORBIDDEN_DISPLAY_CHARS):
        raise ValueError('display_name must not contain ", < or >')
    return value


def _check_allowlist(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if any(not entry for entry in value):
        raise ValueError("tool_allowlist entries must be non-empty")
    return list(dict.fromkeys(value))


class _ConnectionFields(BaseModel):
    display_name: str
    description: str | None = None
    agent: AgentName
    instructions: str | None = Field(default=None, max_length=INSTRUCTIONS_MAX_CHARS)
    tool_allowlist: list[str] | None = None
    enabled: bool = True

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str) -> str:
        return _check_display_name(v)

    @field_validator("tool_allowlist")
    @classmethod
    def _allowlist(cls, v: list[str] | None) -> list[str] | None:
        return _check_allowlist(v)


class GatewayConnectionCreate(_ConnectionFields):
    service_name: str

    @field_validator("service_name")
    @classmethod
    def _service_name(cls, v: str) -> str:
        return validate_service_name(v)


class GatewayConnectionUpdate(_ConnectionFields):
    model_config = ConfigDict(extra="forbid")


class GatewayConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_name: str
    display_name: str
    description: str | None
    agent: AgentName
    instructions: str | None
    tool_allowlist: list[str] | None
    enabled: bool
    created_by: str | None
    updated_by: str | None
    created_at: datetime | None
    updated_at: datetime | None


class GatewayTestRequest(BaseModel):
    service_name: str

    @field_validator("service_name")
    @classmethod
    def _service_name(cls, v: str) -> str:
        return validate_service_name(v)


class GatewayToolOut(BaseModel):
    name: str
    description: str


class GatewayStatusOut(BaseModel):
    state: Literal[
        "ready",
        "sign_in_required",
        "missing_scope",
        "access_denied",
        "not_found",
        "unavailable",
        "not_registered",
    ]
    message: str | None = None
    sign_in_url: str | None = None
    tools: list[GatewayToolOut] = Field(default_factory=list)
