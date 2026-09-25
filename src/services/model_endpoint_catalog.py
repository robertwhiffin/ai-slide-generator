"""Exact Databricks foundation-model endpoint discovery and validation."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import requests
from databricks.sdk import WorkspaceClient
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


#: Transport exhaustion that the SDK does not wrap in ``DatabricksError``.  Its
#: retry wrapper raises builtin ``TimeoutError`` once ``retry_timeout_seconds``
#: elapses and builtin ``RuntimeError`` once ``max_attempts`` is exceeded; raw
#: ``requests``/socket failures can also escape.  Each is mapped to the typed
#: unavailable outcome without reading the exception text.
_TRANSPORT_FAILURES: tuple[type[BaseException], ...] = (
    TimeoutError,
    RuntimeError,
    requests.exceptions.RequestException,
    OSError,
)


class ModelEndpointCatalog(Protocol):
    def list_system_models(self) -> SystemModelDiscovery: ...

    def validate_custom_endpoint_remote(self, name: str) -> None: ...


_URL_PREFIX = re.compile(r"^\s*(?:https?://|//|[a-z][a-z0-9+.-]*://)", re.IGNORECASE)


#: The SDK interpolates the name unescaped into
#: ``/api/2.0/serving-endpoints/{name}``.  Any separator, query, fragment,
#: percent-escape or ASCII control character would change which workspace path
#: the service principal requests, and so would a bare dot segment.
_PATH_METACHARACTERS = re.compile(r"[/\\?#%\x00-\x1f\x7f]")
_DOT_SEGMENTS = frozenset({".", ".."})


def validate_endpoint_name_policy(name: str) -> None:
    """Reject URL- or path-shaped input without normalizing a valid endpoint name."""
    if (
        _URL_PREFIX.match(name)
        or _PATH_METACHARACTERS.search(name)
        or name in _DOT_SEGMENTS
    ):
        raise EndpointValidationFailure(
            "endpoint_url_not_allowed",
            "Endpoint must be a Databricks endpoint name, not a URL.",
            False,
        )


#: The remote check runs while the save holds the exclusive draft lock, so its
#: client must not inherit the SDK's 300 s default retry window.  With a 5 s
#: window and a 3 s per-request timeout, measured transport exhaustion ends
#: well inside the ruled 15 s bound (see ``bounded_catalog_workspace_client``).
CATALOG_RETRY_TIMEOUT_SECONDS = 5
CATALOG_HTTP_TIMEOUT_SECONDS = 3


#: Discovery holds no draft lock, so it gets its own, longer but still finite
#: bound: a slow-but-healthy ``list()`` must not read as unavailable, and an
#: outage must still end rather than wait out the SDK's 300 s default.
DISCOVERY_RETRY_TIMEOUT_SECONDS = 30
DISCOVERY_HTTP_TIMEOUT_SECONDS = 30


def _derived_workspace_client(
    system_client: WorkspaceClient,
    *,
    retry_timeout_seconds: int,
    http_timeout_seconds: int,
) -> WorkspaceClient:
    """Derive a bounded client from the system client's own config.

    No credential source is introduced: the copy keeps the system client's host
    and resolved header factory.  ``Config.copy`` is shallow and shares its
    attribute mapping with the source, so the copy gets its own mapping before
    the timeouts change; the system client's configuration is never modified.
    """
    config = system_client.config.copy()
    config._inner = dict(config._inner)
    config.retry_timeout_seconds = retry_timeout_seconds
    config.http_timeout_seconds = http_timeout_seconds
    return WorkspaceClient(config=config)


def bounded_catalog_workspace_client(system_client: WorkspaceClient) -> WorkspaceClient:
    """The save path's short-retry catalog client (it runs under the draft lock)."""
    return _derived_workspace_client(
        system_client,
        retry_timeout_seconds=CATALOG_RETRY_TIMEOUT_SECONDS,
        http_timeout_seconds=CATALOG_HTTP_TIMEOUT_SECONDS,
    )


def bounded_discovery_workspace_client(system_client: WorkspaceClient) -> WorkspaceClient:
    """The discovery route's catalog client (no lock held; longer finite bound)."""
    return _derived_workspace_client(
        system_client,
        retry_timeout_seconds=DISCOVERY_RETRY_TIMEOUT_SECONDS,
        http_timeout_seconds=DISCOVERY_HTTP_TIMEOUT_SECONDS,
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
        except (DatabricksError, *_TRANSPORT_FAILURES) as error:
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
        # Defensive: never let a path-shaped name reach the interpolated request.
        validate_endpoint_name_policy(name)
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
        except (DatabricksError, *_TRANSPORT_FAILURES) as error:
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
