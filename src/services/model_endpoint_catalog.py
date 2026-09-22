"""Exact Databricks foundation-model endpoint discovery and validation."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from databricks.sdk.errors import DatabricksError, PermissionDenied, ResourceDoesNotExist
from databricks.sdk.service.serving import EndpointStateConfigUpdate, EndpointStateReady

CatalogFailureCode = Literal["catalog_forbidden", "catalog_unavailable"]
EndpointValidationCode = Literal[
    "endpoint_url_not_allowed",
    "endpoint_unknown",
    "endpoint_forbidden",
    "endpoint_unavailable",
    "endpoint_name_mismatch",
    "endpoint_not_ready",
    "endpoint_update_in_progress",
    "endpoint_update_failed",
    "endpoint_update_canceled",
]


@dataclass(frozen=True)
class SystemModelEndpoint:
    name: str
    display_name: str | None
    description: str | None
    docs: str | None


@dataclass(frozen=True)
class SystemModelDiscovery:
    endpoints: tuple[SystemModelEndpoint, ...]


class ModelEndpointCatalogFailure(RuntimeError):  # noqa: N818
    def __init__(self, code: CatalogFailureCode, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class EndpointValidationFailure(ValueError):  # noqa: N818
    def __init__(
        self,
        code: EndpointValidationCode,
        message: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ModelEndpointCatalog(Protocol):
    def list_system_models(self) -> SystemModelDiscovery: ...

    def validate_custom_endpoint_remote(self, name: str) -> None: ...


_URL_PREFIX = re.compile(r"^\s*(?:https?://|//|[a-z][a-z0-9+.-]*://)", re.IGNORECASE)


def validate_endpoint_name_policy(name: str) -> None:
    """Reject URL-shaped input without normalizing a valid endpoint name."""
    if _URL_PREFIX.match(name):
        raise EndpointValidationFailure(
            "endpoint_url_not_allowed",
            "Endpoint must be a Databricks endpoint name, not a URL.",
            False,
        )


class DatabricksModelEndpointCatalog:
    def __init__(self, workspace_client: Any) -> None:
        self._workspace_client = workspace_client

    def list_system_models(self) -> SystemModelDiscovery:
        try:
            endpoints = tuple(self._workspace_client.serving_endpoints.list())
        except PermissionDenied as error:
            raise ModelEndpointCatalogFailure(
                "catalog_forbidden",
                "Model endpoint discovery is not permitted with this workspace identity.",
                False,
            ) from error
        except DatabricksError as error:
            raise ModelEndpointCatalogFailure(
                "catalog_unavailable",
                "Model endpoint discovery is temporarily unavailable. Retry the request.",
                True,
            ) from error

        discovered: list[SystemModelEndpoint] = []
        for endpoint in endpoints:
            served_entities = getattr(endpoint.config, "served_entities", None) or ()
            foundation_model = next(
                (
                    getattr(entity, "foundation_model", None)
                    for entity in served_entities
                    if getattr(entity, "foundation_model", None) is not None
                ),
                None,
            )
            if foundation_model is None:
                continue

            name = getattr(endpoint, "name", None)
            if not isinstance(name, str) or not name.strip():
                raise ModelEndpointCatalogFailure(
                    "catalog_unavailable",
                    "Model endpoint discovery returned an endpoint without a name.",
                    True,
                )

            discovered.append(
                SystemModelEndpoint(
                    name=name,
                    display_name=getattr(foundation_model, "display_name", None),
                    description=getattr(foundation_model, "description", None),
                    docs=getattr(foundation_model, "docs", None),
                )
            )

        discovered.sort(key=lambda item: ((item.display_name or item.name).casefold(), item.name))
        return SystemModelDiscovery(endpoints=tuple(discovered))

    def validate_custom_endpoint_remote(self, name: str) -> None:
        try:
            detail = self._workspace_client.serving_endpoints.get(name)
        except ResourceDoesNotExist as error:
            raise _validation_failure(
                "endpoint_unknown", "Endpoint name was not found.", False
            ) from error
        except PermissionDenied as error:
            raise _validation_failure(
                "endpoint_forbidden",
                "Endpoint cannot be validated with this workspace identity.",
                False,
            ) from error
        except DatabricksError as error:
            raise _validation_failure(
                "endpoint_unavailable",
                "Endpoint validation is temporarily unavailable. Retry the save.",
                True,
            ) from error

        if getattr(detail, "name", None) != name:
            raise _validation_failure(
                "endpoint_name_mismatch",
                "Endpoint validation did not return the exact requested name.",
                False,
            )

        state = getattr(detail, "state", None)
        config_update = getattr(state, "config_update", None)
        if config_update == EndpointStateConfigUpdate.IN_PROGRESS:
            raise _validation_failure(
                "endpoint_update_in_progress",
                "Endpoint configuration update is in progress.",
                True,
            )
        if config_update == EndpointStateConfigUpdate.UPDATE_FAILED:
            raise _validation_failure(
                "endpoint_update_failed",
                "Endpoint configuration update failed.",
                False,
            )
        if config_update == EndpointStateConfigUpdate.UPDATE_CANCELED:
            raise _validation_failure(
                "endpoint_update_canceled",
                "Endpoint configuration update was canceled.",
                False,
            )
        if (
            getattr(state, "ready", None) != EndpointStateReady.READY
            or config_update != EndpointStateConfigUpdate.NOT_UPDATING
        ):
            raise _validation_failure(
                "endpoint_not_ready",
                "Endpoint is not ready for invocation.",
                True,
            )


def _validation_failure(
    code: EndpointValidationCode,
    message: str,
    retryable: bool,
) -> EndpointValidationFailure:
    return EndpointValidationFailure(code, message, retryable)


class FakeModelEndpointCatalog:
    """Deterministic catalog outcomes for tests without an SDK client."""

    def __init__(
        self,
        *,
        discovery_outcomes: list[SystemModelDiscovery | ModelEndpointCatalogFailure]
        | None = None,
        validation_outcomes: dict[str, list[EndpointValidationFailure | None]] | None = None,
    ) -> None:
        self._discovery_outcomes = deque(discovery_outcomes or [SystemModelDiscovery(())])
        self._validation_outcomes = {
            name: deque(outcomes)
            for name, outcomes in (validation_outcomes or {}).items()
        }
        self.list_calls = 0
        self.validated_names: list[str] = []

    def list_system_models(self) -> SystemModelDiscovery:
        self.list_calls += 1
        outcome = self._discovery_outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def validate_custom_endpoint_remote(self, name: str) -> None:
        self.validated_names.append(name)
        outcomes = self._validation_outcomes.get(name)
        if outcomes is None:
            return
        outcome = outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
