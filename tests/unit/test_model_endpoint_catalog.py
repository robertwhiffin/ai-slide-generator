from types import SimpleNamespace

import pytest
from databricks.sdk.errors import DatabricksError, PermissionDenied, ResourceDoesNotExist
from databricks.sdk.service.serving import EndpointStateConfigUpdate, EndpointStateReady

from src.services.model_endpoint_catalog import (
    DatabricksModelEndpointCatalog,
    EndpointValidationFailure,
    FakeModelEndpointCatalog,
    ModelEndpointCatalogFailure,
    SystemModelDiscovery,
    SystemModelEndpoint,
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
