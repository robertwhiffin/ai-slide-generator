"""Promote chosen agent configurations into the frozen Graph Version 1 manifest.

``promote`` rewrites three hash-pinned artefacts (all resolved under ``repo_root``):

* ``src/services/agent_definition_manifest_v1.py`` -- the frozen v1 manifest;
* ``tests/unit/test_packaged_release_loader.py`` -- ``PACKAGED_V1_CONTENT_HASHES``;
* ``tests/unit/test_graph_definition_manifest.py`` -- ``PACKAGED_V1_CONTENT_HASHES``.

Promoted definitions are edited IN PLACE in the parsed manifest JSON (only the fields a
config can change), so unchanged roles stay byte-identical. Every refusal raises
``PromoteBlocked`` before anything is written; all new file texts are computed first and
written only once every check has passed.
"""

from __future__ import annotations

import ast
import importlib
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import src.core.database  # noqa: F401  (break the src.* import cycle first)

from evals.harness.case import EVALS_DIR
from evals.harness.config import AgentEvalConfig
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    GraphV1Manifest,
    definition_content_hash,
)
from src.services.prompt_assembler import _transition_records

MANIFEST_REL = "src/services/agent_definition_manifest_v1.py"
PIN_RELS = (
    "tests/unit/test_packaged_release_loader.py",
    "tests/unit/test_graph_definition_manifest.py",
)
MANIFEST_HEADER = (
    '"""Generated Graph Version 1 Agent Definition snapshot. Do not edit by hand."""\n\n'
)
MANIFEST_VAR = "GRAPH_VERSION_1_MANIFEST_JSON"
PIN_VAR = "PACKAGED_V1_CONTENT_HASHES"
MODEL_FIELDS = ("endpoint_name", "temperature", "max_tokens", "top_p")
CONTRACT_COMMAND = (
    "DATABASE_URL=sqlite:////tmp/tellr-contract-rerecord.db "
    "python -m tests.integration.graph_lifecycle_journey "
    "--write-contract frontend/tests/fixtures/graphLifecycleContract.json"
)


class PromoteBlocked(RuntimeError):
    """Raised for every refusal; nothing has been written when it is raised."""


def _default_repo_root() -> Path:
    return EVALS_DIR.parent


def _read_manifest_json(text: str) -> str:
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == MANIFEST_VAR for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise PromoteBlocked(f"{MANIFEST_VAR} not found in {MANIFEST_REL}")


def _serialise_manifest(parsed: dict) -> str:
    new_json = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
    return MANIFEST_HEADER + f"{MANIFEST_VAR} = " + repr(new_json) + "\n"


def _json_value(value: object) -> object:
    return float(value) if isinstance(value, Decimal) else value


def _rewrite_pins(text: str, rel: str, changes: dict[str, tuple[str, str]]) -> str:
    """Swap ``"role": "old"`` for the new hash, only inside the pinned-hash block."""
    marker = f"{PIN_VAR} = {{"
    if text.count(marker) != 1:
        roles = ", ".join(changes)
        raise PromoteBlocked(f"{rel}: expected exactly one {PIN_VAR} block (roles: {roles})")
    start = text.index(marker)
    end = text.index("}", start)
    block = text[start:end]
    for role, (old, new) in changes.items():
        old_entry = f'"{role}": "{old}"'
        count = block.count(old_entry)
        if count != 1:
            raise PromoteBlocked(
                f"{rel}: pinned entry for {role!r} ({old}) found {count} times in "
                f"{PIN_VAR}; expected exactly once"
            )
        block = block.replace(old_entry, f'"{role}": "{new}"')
    return text[:start] + block + text[end:]


def promote(
    chosen: Mapping[str, AgentEvalConfig],
    *,
    dry_run: bool = False,
    repo_root: Path | None = None,
    run_ids: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Promote ``chosen`` configs into Graph Version 1; return ``{role: new_hash}``."""
    root = Path(repo_root) if repo_root is not None else _default_repo_root()
    manifest_path = root / MANIFEST_REL
    original_manifest_text = manifest_path.read_text(encoding="utf-8")
    parsed = json.loads(_read_manifest_json(original_manifest_text))
    current = GraphV1Manifest.model_validate(parsed)
    current.assert_complete(GRAPH_V1_AGENT_KEYS)
    current_by_key = {d.agent_key: d for d in current.definitions}
    old_hashes = {k: definition_content_hash(d) for k, d in current_by_key.items()}

    # --- validate every choice before touching anything -------------------
    locked = {t.agent_key for t in _transition_records()}
    for role, cfg in chosen.items():
        if role not in GRAPH_V1_AGENT_KEYS:
            raise PromoteBlocked(f"unknown role {role!r}; valid roles: {list(GRAPH_V1_AGENT_KEYS)}")
        if cfg.agent_key != role:
            raise PromoteBlocked(
                f"chosen[{role!r}] holds a config for {cfg.agent_key!r}, not {role!r}"
            )
        if definition_content_hash(cfg.content) != cfg.content_hash:
            raise PromoteBlocked(
                f"{role}: config content_hash {cfg.content_hash} does not match its content"
            )
        if role in locked and cfg.content.prompt_text != current_by_key[role].prompt_text:
            raise PromoteBlocked(
                f"{role}: prompt_text change is blocked -- its v1 prompt is the source of a "
                "LegacyV1PromptTransition; changing it needs a deliberate migration"
            )

    # --- edit the parsed JSON in place -------------------------------------
    prompt_changed: list[str] = []
    for definition in parsed["definitions"]:
        role = definition["agent_key"]
        if role not in chosen:
            continue
        new = chosen[role].content
        old = current_by_key[role]
        if new.prompt_text != old.prompt_text:
            definition["prompt_text"] = new.prompt_text
            prompt_changed.append(role)
        for field in MODEL_FIELDS:
            new_value = getattr(new.model, field)
            if new_value != getattr(old.model, field):
                definition["model"][field] = _json_value(new_value)

    new_manifest_text = _serialise_manifest(parsed)
    new_manifest = GraphV1Manifest.model_validate_json(_read_manifest_json(new_manifest_text))
    new_manifest.assert_complete(GRAPH_V1_AGENT_KEYS)
    new_hashes = {d.agent_key: definition_content_hash(d) for d in new_manifest.definitions}
    for role, cfg in chosen.items():
        if new_hashes[role] != cfg.content_hash:
            raise PromoteBlocked(
                f"{role}: promoted manifest hash {new_hashes[role]} != evaluated config hash "
                f"{cfg.content_hash}"
            )

    changes = {
        role: (old_hashes[role], new_hashes[role])
        for role in GRAPH_V1_AGENT_KEYS
        if new_hashes[role] != old_hashes[role]
    }

    # --- compute every new file text (refusals still possible here) -------
    writes: dict[Path, str] = {}
    if changes:
        writes[manifest_path] = new_manifest_text
        for rel in PIN_RELS:
            path = root / rel
            writes[path] = _rewrite_pins(path.read_text(encoding="utf-8"), rel, changes)

    if run_ids:
        print("MLflow run ids (for the commit message):")
        for role, run_id in run_ids.items():
            print(f"  {role}: {run_id}")

    if dry_run:
        return new_hashes

    for path, text in writes.items():
        path.write_text(text, encoding="utf-8")

    if changes:
        print("Promoted roles: " + ", ".join(f"{r} {o[:12]} -> {n[:12]}" for r, (o, n) in changes.items()))
        print("Re-record the frontend lifecycle contract (it embeds every v1 prompt and hash):")
        print(f"  {CONTRACT_COMMAND}")
        for role in prompt_changed:
            instructions = getattr(importlib.import_module(f"src.core.skills.{role}"), "INSTRUCTIONS", None)
            if instructions != chosen[role].content.prompt_text:
                print(
                    f"Skill body drift: src/core/skills/{role}.py INSTRUCTIONS no longer matches "
                    f"the promoted {role} prompt_text (promote does not edit skill files)."
                )
    return new_hashes
