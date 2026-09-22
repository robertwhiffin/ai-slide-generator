"""Generate the checked-in Graph Version 1 Agent Definition snapshot.

This is a one-shot developer tool. Production loads only the generated Python data
module and never derives Graph Version 1 from the compatibility source.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.services.agent_runtime import (  # noqa: E402
    MODEL_DRIVEN_AGENT_KEYS,
    CodeOwnedAgentDefinitionSource,
)
from src.services.graph_definition_manifest import (  # noqa: E402
    DefinitionContent,
    GraphV1Manifest,
    assembly_rules_for,
)

_HEADER = (
    '"""Generated Graph Version 1 Agent Definition snapshot. Do not edit by hand."""\n\n'
)


def build_manifest() -> GraphV1Manifest:
    source = CodeOwnedAgentDefinitionSource()
    definitions = []
    for agent_key in MODEL_DRIVEN_AGENT_KEYS:
        current = source.resolve(agent_key)
        definitions.append(
            DefinitionContent.model_validate(
                {
                    "agent_key": current.agent_key,
                    "definition_version": current.definition_version,
                    "prompt_text": current.prompt_text,
                    "model": dataclasses.asdict(current.model_configuration),
                    "schema_overlay": {
                        "field_overrides": {},
                        "additional_optional_fields": [],
                    },
                    "assembly_rules": assembly_rules_for(agent_key),
                    "protected_assembly": {
                        "version": current.protected_prompt.version,
                        "digest": current.protected_prompt.digest,
                    },
                    "schema_contract": {
                        "version": current.schema_contract.version,
                        "digest": current.schema_contract.digest,
                    },
                }
            )
        )
    return GraphV1Manifest(manifest_version=1, definitions=tuple(definitions))


def build_manifest_json() -> str:
    return json.dumps(
        build_manifest().model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def render_manifest_module(json_text: str) -> str:
    """Render JSON as an escaped Python literal safe for arbitrary prompt bytes."""
    return _HEADER + f"GRAPH_VERSION_1_MANIFEST_JSON = {json_text!r}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "src"
            / "services"
            / "agent_definition_manifest_v1.py"
        ),
    )
    args = parser.parse_args()
    args.output.write_text(render_manifest_module(build_manifest_json()))


if __name__ == "__main__":
    main()
