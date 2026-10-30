"""Task 9b: the graph engine's builder runs on Claude Sonnet, and only the builder moved.

The frozen Graph Version 1 manifest (``src/services/agent_definition_manifest_v1.py``)
ran the builder on ``system.ai.claude-haiku-4-5``.  The owner chose (2026-10-30) to
run it on the newest Claude Sonnet whose rate limits are non-zero.  The
``tellr-dev`` AI Gateway catalogue (``DatabricksModelEndpointCatalog.list_system_models``)
offers ``system.ai.claude-sonnet-5-5`` with no service-wide rate limit set, so the
builder's endpoint is pinned to that.

The manifest is parsed the way ``evals.harness.promote`` reads it
(``_read_manifest_json`` over the file text), then cross-checked against the
packaged loader the app uses at runtime.

* ``test_builder_endpoint_is_sonnet`` is red until the manifest switches the builder.
* The other tests are green both before and after.  They pin every other role's model,
  plus the builder's sampling settings, as literals, so any accidental change fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.core.database  # noqa: F401  (must be imported before other src.* modules)
from evals.harness.promote import MANIFEST_REL, _read_manifest_json
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS, load_graph_v1_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]

BUILDER_SONNET_ENDPOINT = "system.ai.claude-sonnet-5-5"

#: Every non-builder role's model block as it stood before Task 9b, copied from the manifest.
OTHER_ROLE_MODELS: dict[str, dict[str, object]] = {
    "architect": {
        "endpoint_name": "system.ai.claude-opus-5-5",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95,
    },
    "data_analyst": {
        "endpoint_name": "system.ai.claude-opus-5-5",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95,
    },
    "build_reviewer": {
        "endpoint_name": "system.ai.claude-opus-5-5",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95,
    },
    "fixer": {
        "endpoint_name": "system.ai.claude-opus-5-5",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95,
    },
    "fix_reviewer": {
        "endpoint_name": "system.ai.claude-haiku-4-5",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95,
    },
    "deck_reviewer": {
        "endpoint_name": "system.ai.claude-haiku-4-5",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95,
    },
}

#: The builder's sampling settings, unchanged by the model switch.
BUILDER_SAMPLING: dict[str, object] = {"temperature": 0.7, "max_tokens": 60000, "top_p": 0.95}


def _manifest_models() -> dict[str, dict[str, object]]:
    text = (REPO_ROOT / MANIFEST_REL).read_text(encoding="utf-8")
    parsed = json.loads(_read_manifest_json(text))
    models: dict[str, dict[str, object]] = {}
    for definition in parsed["definitions"]:
        key = definition["agent_key"]
        assert key not in models, f"duplicate definition for {key!r} in the manifest"
        models[key] = definition["model"]
    return models


def test_manifest_roles_are_the_graph_v1_roles() -> None:
    models = _manifest_models()
    assert set(models) == set(GRAPH_V1_AGENT_KEYS)
    assert set(OTHER_ROLE_MODELS) == set(GRAPH_V1_AGENT_KEYS) - {"builder"}


def test_builder_endpoint_is_sonnet() -> None:
    assert _manifest_models()["builder"]["endpoint_name"] == BUILDER_SONNET_ENDPOINT


def test_packaged_loader_agrees_on_builder_endpoint() -> None:
    # The app reads the manifest through this loader; it must see the same builder model
    # that promote's parser sees.
    loaded = {d.agent_key: d.model for d in load_graph_v1_manifest().definitions}
    assert loaded["builder"].endpoint_name == _manifest_models()["builder"]["endpoint_name"]


def test_builder_sampling_unchanged() -> None:
    builder = _manifest_models()["builder"]
    assert {k: v for k, v in builder.items() if k != "endpoint_name"} == BUILDER_SAMPLING


@pytest.mark.parametrize("role", sorted(OTHER_ROLE_MODELS))
def test_other_role_model_unchanged(role: str) -> None:
    models = _manifest_models()
    assert role in models, f"{role!r} is missing from the manifest"
    assert models[role] == OTHER_ROLE_MODELS[role]
