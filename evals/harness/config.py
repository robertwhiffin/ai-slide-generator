"""Eval configuration loader.

Loads YAML override files that describe a named eval variant for one agent role,
starting from the frozen v1 manifest and applying field-level overrides.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)

_PRICES_PATH = Path(__file__).parent.parent / "configs" / "prices.yaml"


class ConfigError(ValueError):
    """Raised for invalid or unrecognised eval-config fields."""


_KNOWN_KEYS = frozenset({
    "agent_key", "name", "base", "prompt_text", "prompt_file",
    "endpoint_name", "temperature", "max_tokens", "top_p",
})


@dataclass(frozen=True)
class AgentEvalConfig:
    agent_key: str
    name: str
    content: DefinitionContent
    content_hash: str


def v1_baseline(agent_key: str) -> AgentEvalConfig:
    """Return the unmodified v1 definition for *agent_key* with name='v1-baseline'."""
    if agent_key not in GRAPH_V1_AGENT_KEYS:
        raise ConfigError(
            f"agent_key {agent_key!r} is not a valid v1 agent key; "
            f"valid keys are {list(GRAPH_V1_AGENT_KEYS)}"
        )
    manifest_by_key = {d.agent_key: d for d in load_graph_v1_manifest().definitions}
    content = manifest_by_key[agent_key]
    return AgentEvalConfig(
        agent_key=agent_key,
        name="v1-baseline",
        content=content,
        content_hash=definition_content_hash(content),
    )


def load_config(path: str | Path) -> AgentEvalConfig:
    """Load an eval config from a YAML file at *path*.

    YAML fields
    -----------
    agent_key      : str   (required) — must be in GRAPH_V1_AGENT_KEYS
    name           : str   (required) — human label for this config
    base           : str   (optional, default "v1") — only "v1" is supported today
    prompt_text    : str   (optional) — inline replacement for the authored prompt
    prompt_file    : str   (optional) — path relative to the YAML file
    endpoint_name  : str   (optional) — override model endpoint
    temperature    : float (optional)
    max_tokens     : int   (optional)
    top_p          : float (optional)
    """
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: config must be a YAML mapping")
    unknown = sorted(set(raw) - _KNOWN_KEYS)
    if unknown:
        raise ConfigError(
            f"{path}: unknown config key(s) {unknown}; valid keys are {sorted(_KNOWN_KEYS)}"
        )
    base = raw.get("base", "v1")
    if base != "v1":
        raise ConfigError(f"{path}: base {base!r} is not supported; only base: v1 exists")

    agent_key = raw.get("agent_key")
    if agent_key not in GRAPH_V1_AGENT_KEYS:
        raise ConfigError(
            f"agent_key {agent_key!r} is not a valid v1 agent key; "
            f"valid keys are {list(GRAPH_V1_AGENT_KEYS)}"
        )

    name = raw.get("name", agent_key)

    # Start from the v1 base definition.
    manifest_by_key = {d.agent_key: d for d in load_graph_v1_manifest().definitions}
    content: DefinitionContent = manifest_by_key[agent_key]

    # Apply ModelConfiguration overrides (model_copy bypasses frozen restriction).
    _MODEL_FIELDS = ("endpoint_name", "temperature", "max_tokens", "top_p")
    model_overrides = {f: raw[f] for f in _MODEL_FIELDS if f in raw}
    if model_overrides:
        new_model = content.model.model_copy(update=model_overrides)
        content = content.model_copy(update={"model": new_model})

    # Apply prompt override (inline text takes precedence over file).
    if "prompt_text" in raw:
        content = content.model_copy(update={"prompt_text": raw["prompt_text"]})
    elif "prompt_file" in raw:
        prompt_path = path.parent / raw["prompt_file"]
        content = content.model_copy(update={"prompt_text": prompt_path.read_text()})

    # model_copy skips validation, so re-validate the rebuilt content: an out-of-range override
    # (max_tokens: -5, temperature: 9) must fail here, naming the field, not reach a model call.
    try:
        content = DefinitionContent.model_validate(content.model_dump())
    except ValidationError as e:
        fields = sorted({".".join(str(x) for x in err["loc"]) for err in e.errors()})
        raise ConfigError(f"{path}: invalid value for {fields}: {e}") from e

    return AgentEvalConfig(
        agent_key=agent_key,
        name=name,
        content=content,
        content_hash=definition_content_hash(content),
    )


def prices() -> dict[str, dict]:
    """Parse *evals/configs/prices.yaml* → ``{endpoint: {input_per_1k, output_per_1k}}``."""
    with open(_PRICES_PATH) as f:
        raw = yaml.safe_load(f) or {}
    return {k: dict(v) for k, v in raw.items()}
