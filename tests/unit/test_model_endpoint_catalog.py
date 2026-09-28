from types import SimpleNamespace

import pytest
import requests
from databricks.sdk.errors import DatabricksError, NotFound, PermissionDenied

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
    gateway_endpoint_name,
    gateway_invocable_name,
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


class RecordingApiClient:
    def __init__(self, *, responses=None, errors=None):
        self.responses = dict(responses or {})
        self.errors = dict(errors or {})
        self.calls: list[tuple[str, str]] = []

    def do(self, method, path, **kwargs):
        assert not kwargs, f"unexpected request options: {kwargs}"
        self.calls.append((method, path))
        if path in self.errors:
            raise self.errors[path]
        return self.responses[path]


def gateway_catalog(api_client):
    return DatabricksModelEndpointCatalog(SimpleNamespace(api_client=api_client))


LIST_PATH = "/api/ai-gateway/v2/endpoints"


def test_list_system_models_maps_gateway_endpoints_to_system_ai_names_sorted():
    api = RecordingApiClient(responses={LIST_PATH: {"endpoints": [
        {"name": "databricks-gpt-oss-120b"},
        {"name": "databricks-claude-opus-5-5"},
        {"name": "databricks-bge-large-en"},
    ]}})

    discovery = gateway_catalog(api).list_system_models()

    assert api.calls == [("GET", LIST_PATH)]
    assert [item.name for item in discovery.endpoints] == [
        "system.ai.bge-large-en",
        "system.ai.claude-opus-5-5",
        "system.ai.gpt-oss-120b",
    ]
    assert all(
        (item.display_name, item.description, item.docs) == (None, None, None)
        for item in discovery.endpoints
    )


def test_list_system_models_drops_names_without_the_databricks_prefix():
    api = RecordingApiClient(responses={LIST_PATH: {"endpoints": [
        {"name": "my-provisioned-endpoint"},
        {"name": "databricks-gemma-3-12b"},
    ]}})

    assert [item.name for item in gateway_catalog(api).list_system_models().endpoints] == [
        "system.ai.gemma-3-12b"
    ]


def test_list_system_models_returns_empty_success_for_no_endpoints():
    api = RecordingApiClient(responses={LIST_PATH: {}})

    assert gateway_catalog(api).list_system_models() == SystemModelDiscovery(endpoints=())


def test_list_system_models_refuses_an_entry_without_a_name():
    api = RecordingApiClient(responses={LIST_PATH: {"endpoints": [{"id": "x"}]}})

    with pytest.raises(ModelEndpointCatalogFailure) as caught:
        gateway_catalog(api).list_system_models()
    assert caught.value.code == "catalog_unavailable"


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (PermissionDenied("PROVIDER_SECRET"), "catalog_forbidden", False),
        (DatabricksError("PROVIDER_SECRET"), "catalog_unavailable", True),
        (TimeoutError("PROVIDER_SECRET"), "catalog_unavailable", True),
        (requests.exceptions.ConnectionError("PROVIDER_SECRET"), "catalog_unavailable", True),
    ],
)
def test_list_system_models_maps_gateway_failures(error, code, retryable):
    api = RecordingApiClient(errors={LIST_PATH: error})

    with pytest.raises(ModelEndpointCatalogFailure) as caught:
        gateway_catalog(api).list_system_models()
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert "PROVIDER_SECRET" not in str(caught.value)


@pytest.mark.parametrize(
    ("gateway", "invocable"),
    [
        ("databricks-claude-opus-5-5", "system.ai.claude-opus-5-5"),
        ("databricks-", None),
        ("claude-opus-5-5", None),
        ("xdatabricks-claude", None),
    ],
)
def test_gateway_invocable_name(gateway, invocable):
    assert gateway_invocable_name(gateway) == invocable


@pytest.mark.parametrize(
    ("model", "gateway"),
    [
        ("system.ai.claude-opus-5-5", "databricks-claude-opus-5-5"),
        ("databricks-claude-opus-4-6", "databricks-claude-opus-4-6"),
    ],
)
def test_gateway_endpoint_name(model, gateway):
    assert gateway_endpoint_name(model) == gateway


def detail_path(gateway_name):
    return f"{LIST_PATH}/{gateway_name}"


def test_remote_check_looks_up_the_mapped_gateway_endpoint_once():
    path = detail_path("databricks-claude-opus-5-5")
    api = RecordingApiClient(responses={path: {
        "name": "databricks-claude-opus-5-5",
        "supported_api_types": ["mlflow/v1/chat/completions", "anthropic/v1/messages"],
    }})

    assert gateway_catalog(api).validate_custom_endpoint_remote("system.ai.claude-opus-5-5") is None
    assert api.calls == [("GET", path)]


def test_remote_check_looks_up_a_legacy_name_as_is():
    path = detail_path("databricks-claude-opus-4-6")
    api = RecordingApiClient(responses={path: {
        "name": "databricks-claude-opus-4-6",
        "supported_api_types": ["mlflow/v1/chat/completions"],
    }})

    gateway_catalog(api).validate_custom_endpoint_remote("databricks-claude-opus-4-6")
    assert api.calls == [("GET", path)]


def test_remote_check_refuses_an_embedding_endpoint():
    path = detail_path("databricks-bge-large-en")
    api = RecordingApiClient(responses={path: {
        "name": "databricks-bge-large-en",
        "supported_api_types": ["mlflow/v1/embeddings"],
    }})

    with pytest.raises(EndpointValidationFailure) as caught:
        gateway_catalog(api).validate_custom_endpoint_remote("system.ai.bge-large-en")
    assert (caught.value.code, caught.value.message, caught.value.retryable) == (
        "endpoint_not_chat_model", "Endpoint is not a chat model.", False,
    )


def test_remote_check_refuses_a_detail_without_api_types():
    path = detail_path("databricks-x")
    api = RecordingApiClient(responses={path: {"name": "databricks-x"}})

    with pytest.raises(EndpointValidationFailure) as caught:
        gateway_catalog(api).validate_custom_endpoint_remote("system.ai.x")
    assert caught.value.code == "endpoint_not_chat_model"


@pytest.mark.parametrize(
    ("error", "code", "message", "retryable"),
    [
        (NotFound("PROVIDER_SECRET"), "endpoint_unknown", "Endpoint name was not found.", False),
        (PermissionDenied("PROVIDER_SECRET"), "endpoint_forbidden",
         "Endpoint cannot be validated with this workspace identity.", False),
        (DatabricksError("PROVIDER_SECRET"), "endpoint_unavailable",
         "Endpoint validation is temporarily unavailable. Retry the save.", True),
        (TimeoutError("PROVIDER_SECRET"), "endpoint_unavailable",
         "Endpoint validation is temporarily unavailable. Retry the save.", True),
        (RuntimeError("Exceeded max retry attempts (3)"), "endpoint_unavailable",
         "Endpoint validation is temporarily unavailable. Retry the save.", True),
        (requests.exceptions.ConnectionError("PROVIDER_SECRET"), "endpoint_unavailable",
         "Endpoint validation is temporarily unavailable. Retry the save.", True),
        (OSError("PROVIDER_SECRET"), "endpoint_unavailable",
         "Endpoint validation is temporarily unavailable. Retry the save.", True),
    ],
)
def test_remote_check_maps_gateway_lookup_failures(error, code, message, retryable):
    api = RecordingApiClient(errors={detail_path("databricks-m"): error})

    with pytest.raises(EndpointValidationFailure) as caught:
        gateway_catalog(api).validate_custom_endpoint_remote("system.ai.m")
    assert (caught.value.code, caught.value.message, caught.value.retryable) == (code, message, retryable)
    assert "PROVIDER_SECRET" not in caught.value.message


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
    api = RecordingApiClient()

    with pytest.raises(EndpointValidationFailure) as failure:
        gateway_catalog(api).validate_custom_endpoint_remote(name)

    assert failure.value.code == "endpoint_url_not_allowed"
    assert api.calls == []


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
        ("GET", "https://unit.invalid/api/ai-gateway/v2/endpoints/exact endpoint name")
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
