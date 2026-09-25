from types import SimpleNamespace

import pytest
import requests
from databricks.sdk.errors import DatabricksError, PermissionDenied, ResourceDoesNotExist
from databricks.sdk.service.serving import EndpointStateConfigUpdate, EndpointStateReady

from src.services.model_endpoint_catalog import (
    CATALOG_RETRY_TIMEOUT_SECONDS,
    DatabricksModelEndpointCatalog,
    EndpointValidationFailure,
    FakeModelEndpointCatalog,
    ModelEndpointCatalogFailure,
    SystemModelDiscovery,
    SystemModelEndpoint,
    bounded_catalog_workspace_client,
    bounded_discovery_workspace_client,
    validate_endpoint_name_policy,
)


class RecordingServingEndpoints:
    def __init__(self, *, listed=(), detail=None, list_error=None, get_error=None):
        self.listed = listed
        self.detail = detail
        self.list_error = list_error
        self.get_error = get_error
        self.list_calls = 0
        self.get_calls: list[str] = []

    def list(self):
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return iter(self.listed)

    def get(self, name):
        self.get_calls.append(name)
        if self.get_error is not None:
            raise self.get_error
        return self.detail

    def __getattr__(self, name):
        raise AssertionError(f"unexpected serving API access: {name}")


def catalog_for(serving_endpoints):
    return DatabricksModelEndpointCatalog(
        SimpleNamespace(serving_endpoints=serving_endpoints)
    )


def endpoint(name, *foundation_models, task=None):
    return SimpleNamespace(
        name=name,
        task=task,
        config=SimpleNamespace(
            served_entities=[
                SimpleNamespace(foundation_model=foundation_model)
                for foundation_model in foundation_models
            ]
        ),
    )


def foundation_model(*, display_name=None, description=None, docs=None):
    return SimpleNamespace(
        display_name=display_name,
        description=description,
        docs=docs,
    )


def test_list_system_models_selects_foundation_endpoints_once_and_sorts_exact_names():
    alpha = endpoint(
        "alpha exact name",
        foundation_model(display_name="Zeta", description="alpha", docs="docs-a"),
        foundation_model(display_name="Ignored duplicate", description="duplicate", docs="x"),
    )
    beta = endpoint("beta", foundation_model(display_name="Alpha"))
    task_only = endpoint("task-only", task="llm/v1/chat")
    serving_endpoints = RecordingServingEndpoints(listed=[alpha, task_only, beta])

    discovery = catalog_for(serving_endpoints).list_system_models()

    assert discovery == SystemModelDiscovery(
        endpoints=(
            SystemModelEndpoint("beta", "Alpha", None, None),
            SystemModelEndpoint("alpha exact name", "Zeta", "alpha", "docs-a"),
        )
    )
    assert serving_endpoints.list_calls == 1


def test_list_system_models_returns_empty_success_and_never_fabricates_missing_name():
    empty = catalog_for(RecordingServingEndpoints(listed=[])).list_system_models()
    assert empty == SystemModelDiscovery(endpoints=())

    nameless = endpoint(None, foundation_model(display_name="Foundation"))
    with pytest.raises(ModelEndpointCatalogFailure) as failure:
        catalog_for(RecordingServingEndpoints(listed=[nameless])).list_system_models()

    assert failure.value.code == "catalog_unavailable"
    assert failure.value.retryable is True


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (PermissionDenied("denied"), "catalog_forbidden", False),
        (DatabricksError("unavailable"), "catalog_unavailable", True),
    ],
)
def test_list_system_models_keeps_forbidden_and_unavailable_observable(error, code, retryable):
    with pytest.raises(ModelEndpointCatalogFailure) as failure:
        catalog_for(RecordingServingEndpoints(list_error=error)).list_system_models()

    assert failure.value.code == code
    assert failure.value.retryable is retryable


@pytest.mark.parametrize("url", ["http://host", " https://host", "//host", "dbfs://host"])
def test_validate_endpoint_name_policy_rejects_every_url_shape(url):
    with pytest.raises(EndpointValidationFailure) as failure:
        validate_endpoint_name_policy(url)

    assert failure.value.code == "endpoint_url_not_allowed"
    assert failure.value.retryable is False


def test_validate_endpoint_name_policy_preserves_accepted_input_verbatim():
    name = "  exact endpoint name  "
    assert validate_endpoint_name_policy(name) is None
    assert name == "  exact endpoint name  "


def detailed_endpoint(
    name,
    *,
    ready=EndpointStateReady.READY,
    update=EndpointStateConfigUpdate.NOT_UPDATING,
):
    return SimpleNamespace(
        name=name,
        state=SimpleNamespace(ready=ready, config_update=update),
    )


def test_validate_custom_endpoint_remote_calls_get_once_with_exact_name():
    serving_endpoints = RecordingServingEndpoints(
        detail=detailed_endpoint("exact endpoint name")
    )

    catalog_for(serving_endpoints).validate_custom_endpoint_remote("exact endpoint name")

    assert serving_endpoints.get_calls == ["exact endpoint name"]


@pytest.mark.parametrize(
    ("detail", "error", "code", "retryable"),
    [
        (detailed_endpoint("alias"), None, "endpoint_name_mismatch", False),
        (
            detailed_endpoint("exact", ready=EndpointStateReady.NOT_READY),
            None,
            "endpoint_not_ready",
            True,
        ),
        (
            detailed_endpoint("exact", update=EndpointStateConfigUpdate.IN_PROGRESS),
            None,
            "endpoint_update_in_progress",
            True,
        ),
        (
            detailed_endpoint("exact", update=EndpointStateConfigUpdate.UPDATE_FAILED),
            None,
            "endpoint_update_failed",
            False,
        ),
        (
            detailed_endpoint("exact", update=EndpointStateConfigUpdate.UPDATE_CANCELED),
            None,
            "endpoint_update_canceled",
            False,
        ),
        (None, ResourceDoesNotExist("missing"), "endpoint_unknown", False),
        (None, PermissionDenied("denied"), "endpoint_forbidden", False),
        (None, DatabricksError("unavailable"), "endpoint_unavailable", True),
    ],
)
def test_validate_custom_endpoint_remote_maps_exact_outcomes(detail, error, code, retryable):
    serving_endpoints = RecordingServingEndpoints(detail=detail, get_error=error)

    with pytest.raises(EndpointValidationFailure) as failure:
        catalog_for(serving_endpoints).validate_custom_endpoint_remote("exact")

    assert serving_endpoints.get_calls == ["exact"]
    assert failure.value.code == code
    assert failure.value.retryable is retryable


def test_fake_catalog_queues_discovery_and_name_keyed_validation_outcomes():
    discovery = SystemModelDiscovery(
        endpoints=(SystemModelEndpoint("first", None, None, None),)
    )
    unavailable = EndpointValidationFailure(
        "endpoint_unavailable", "temporarily unavailable", True
    )
    fake = FakeModelEndpointCatalog(
        discovery_outcomes=[discovery],
        validation_outcomes={"first": [None], "second": [unavailable]},
    )

    assert fake.list_system_models() == discovery
    fake.validate_custom_endpoint_remote("first")
    with pytest.raises(EndpointValidationFailure, match="temporarily unavailable"):
        fake.validate_custom_endpoint_remote("second")

    assert fake.list_calls == 1
    assert fake.validated_names == ["first", "second"]


# Correction 3: the SDK retry wrapper exhausts transport failures into builtins
# that are not ``DatabricksError``; both catalog methods must still stay typed.
_TRANSPORT_EXHAUSTION = [
    pytest.param(TimeoutError("Timed out after 0:05:00"), id="sdk-retry-timeout"),
    pytest.param(RuntimeError("Exceeded max retry attempts (3)"), id="sdk-max-attempts"),
    pytest.param(requests.exceptions.ConnectionError("reset"), id="requests-transport"),
    pytest.param(OSError("socket closed"), id="os-transport"),
]


@pytest.mark.parametrize("error", _TRANSPORT_EXHAUSTION)
def test_list_system_models_maps_transport_exhaustion_to_catalog_unavailable(error):
    serving_endpoints = RecordingServingEndpoints(list_error=error)

    with pytest.raises(ModelEndpointCatalogFailure) as failure:
        catalog_for(serving_endpoints).list_system_models()

    assert serving_endpoints.list_calls == 1
    assert failure.value.code == "catalog_unavailable"
    assert failure.value.retryable is True
    assert str(failure.value) == (
        "Model endpoint discovery is temporarily unavailable. Retry the request."
    )
    assert failure.value.__cause__ is error


@pytest.mark.parametrize("error", _TRANSPORT_EXHAUSTION)
def test_validate_custom_endpoint_remote_maps_transport_exhaustion_to_endpoint_unavailable(
    error,
):
    serving_endpoints = RecordingServingEndpoints(get_error=error)

    with pytest.raises(EndpointValidationFailure) as failure:
        catalog_for(serving_endpoints).validate_custom_endpoint_remote("exact")

    assert serving_endpoints.get_calls == ["exact"]
    assert failure.value.code == "endpoint_unavailable"
    assert failure.value.retryable is True
    assert failure.value.message == (
        "Endpoint validation is temporarily unavailable. Retry the save."
    )
    assert failure.value.__cause__ is error


# Correction 4: the SDK interpolates the name unescaped into
# ``/api/2.0/serving-endpoints/{name}``, so path metacharacters and dot segments
# would address another workspace API under the service principal.
_PATH_SHAPED_NAMES = [
    pytest.param("../../2.0/secrets/scopes/list", id="dot-segment-traversal"),
    pytest.param("a/b", id="slash"),
    pytest.param("a\\b", id="backslash"),
    pytest.param("x?y=1", id="query"),
    pytest.param("x#frag", id="fragment"),
    pytest.param("a%2Fb", id="percent-escape"),
    pytest.param("a\x00b", id="nul"),
    pytest.param("a\nb", id="newline"),
    pytest.param("a\tb", id="tab"),
    pytest.param("a\x7fb", id="delete"),
    pytest.param(".", id="dot"),
    pytest.param("..", id="dot-dot"),
]


@pytest.mark.parametrize("name", _PATH_SHAPED_NAMES)
def test_validate_endpoint_name_policy_rejects_request_path_metacharacters(name):
    with pytest.raises(EndpointValidationFailure) as failure:
        validate_endpoint_name_policy(name)

    assert failure.value.code == "endpoint_url_not_allowed"
    assert failure.value.message == (
        "Endpoint must be a Databricks endpoint name, not a URL."
    )
    assert failure.value.retryable is False


@pytest.mark.parametrize(
    "name",
    [
        "databricks-claude-opus-4-6",
        "exact endpoint name",
        "model.v1",
        "...",
        " ..",
        "endpoint_with-mixed.chars",
        "modèle-é",
    ],
)
def test_validate_endpoint_name_policy_accepts_other_endpoint_names_verbatim(name):
    original = str(name)

    assert validate_endpoint_name_policy(name) is None
    assert name == original


@pytest.mark.parametrize("name", _PATH_SHAPED_NAMES)
def test_validate_custom_endpoint_remote_refuses_a_path_shaped_name_before_any_get(name):
    serving_endpoints = RecordingServingEndpoints(detail=detailed_endpoint(name))

    with pytest.raises(EndpointValidationFailure) as failure:
        catalog_for(serving_endpoints).validate_custom_endpoint_remote(name)

    assert failure.value.code == "endpoint_url_not_allowed"
    assert serving_endpoints.get_calls == []


# Controller ruling on correction 8: the remote check runs under the exclusive
# draft lock, so its client must bound the SDK's retry window (default 300 s)
# while reusing the system client's own credentials.
class _SteppingClock:
    """SDK ``Clock`` that advances only when the retry wrapper sleeps."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _offline_system_client(monkeypatch, clock=None):
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.config import Config

    # Host-metadata discovery is the only network step in PAT config resolution.
    monkeypatch.setattr(Config, "_resolve_host_metadata", lambda self: None)
    return WorkspaceClient(
        config=Config(host="https://unit.invalid", token="dapi-unit", clock=clock)
    )


def test_bounded_endpoint_catalog_client_reuses_system_credentials_and_leaves_it_unchanged(
    monkeypatch,
):
    system_client = _offline_system_client(monkeypatch)
    system_inner = dict(system_client.config._inner)

    bounded = bounded_catalog_workspace_client(system_client)

    assert bounded is not system_client
    assert bounded.config.retry_timeout_seconds == CATALOG_RETRY_TIMEOUT_SECONDS
    assert 0 < CATALOG_RETRY_TIMEOUT_SECONDS <= 15
    # Literal pins: a 5 s retry window and a 3 s per-request timeout together
    # keep one hung socket inside the ruled 15 s bound (SDK default is 60 s).
    assert bounded.config.retry_timeout_seconds == 5
    assert bounded.config.http_timeout_seconds == 3
    assert bounded.config.host == system_client.config.host
    # Same credential source: the copy shares the resolved header factory.
    assert bounded.config._header_factory is system_client.config._header_factory
    assert bounded.config.authenticate() == system_client.config.authenticate()
    # The system client's own configuration is never changed.
    assert system_client.config._inner == system_inner
    assert system_client.config.retry_timeout_seconds is None
    assert system_client.config.http_timeout_seconds is None


def test_bounded_endpoint_catalog_client_turns_a_transport_outage_into_endpoint_unavailable(
    monkeypatch,
):
    clock = _SteppingClock()
    system_client = _offline_system_client(monkeypatch, clock=clock)
    requested: list[tuple[str, str]] = []
    transport_timeouts: list[object] = []

    def _refused(self, method, url, **kwargs):
        requested.append((method, url))
        transport_timeouts.append(kwargs.get("timeout"))
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(requests.Session, "request", _refused)
    catalog = DatabricksModelEndpointCatalog(bounded_catalog_workspace_client(system_client))
    started = clock.now

    with pytest.raises(EndpointValidationFailure) as failure:
        catalog.validate_custom_endpoint_remote("exact endpoint name")

    assert failure.value.code == "endpoint_unavailable"
    assert failure.value.retryable is True
    assert isinstance(failure.value.__cause__, TimeoutError)
    assert requested and set(requested) == {
        ("GET", "https://unit.invalid/api/2.0/serving-endpoints/exact endpoint name")
    }
    # Every attempt reached the transport with the bounded 3 s timeout.
    assert transport_timeouts and set(transport_timeouts) == {3}
    # The SDK stops retrying once the bounded window elapses; one final sleep
    # (at most min(10, attempt) + 1 s) may overshoot it.
    elapsed = clock.now - started
    assert CATALOG_RETRY_TIMEOUT_SECONDS <= elapsed <= 15


def test_bounded_discovery_client_has_its_own_finite_bound_and_leaves_the_system_client_unchanged(
    monkeypatch,
):
    """Catches discovery sharing the save path's 5 s/3 s bound or the SDK's unbounded defaults."""
    system_client = _offline_system_client(monkeypatch)
    system_inner = dict(system_client.config._inner)

    discovery = bounded_discovery_workspace_client(system_client)
    save = bounded_catalog_workspace_client(system_client)

    assert discovery is not system_client
    assert discovery.config.retry_timeout_seconds == 30
    assert discovery.config.http_timeout_seconds == 30
    assert save.config.retry_timeout_seconds == 5
    assert save.config.http_timeout_seconds == 3
    assert discovery.config._inner is not save.config._inner
    assert discovery.config.host == system_client.config.host
    assert discovery.config._header_factory is system_client.config._header_factory
    assert system_client.config._inner == system_inner
    assert system_client.config.retry_timeout_seconds is None
    assert system_client.config.http_timeout_seconds is None
