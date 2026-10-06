"""Failing tests for Task 8: ``evals/harness/promote.py``.

``promote`` rewrites three frozen, hash-pinned artefacts:

* ``src/services/agent_definition_manifest_v1.py`` (the Graph Version 1 manifest)
* ``tests/unit/test_packaged_release_loader.py``   (``PACKAGED_V1_CONTENT_HASHES``)
* ``tests/unit/test_graph_definition_manifest.py`` (``PACKAGED_V1_CONTENT_HASHES``)

ISOLATION: every writing test copies those files into ``tmp_path`` (mirroring the
relative paths) and calls ``promote(..., repo_root=tmp_path)``.  The real files are
snapshotted and restored by an autouse fixture, and the LAST test in this module
asserts the real files still equal ``git show HEAD:<path>``.

Names fixed here (see task-8-report.md):
* ``promote.promote(chosen, *, dry_run=False, repo_root=None) -> dict[str, str]``.
* ``promote.PromoteBlocked(RuntimeError)`` is raised for EVERY refusal: transition
  lock, content-hash mismatch, unknown role key, ``chosen`` key != config.agent_key,
  and a pinned-hash entry not found exactly once in a ``PACKAGED_V1_CONTENT_HASHES``
  block.  The message always names the offending role key.
* Transition-lock messages contain the substring ``prompt``.
* Stdout after a real change contains ``--write-contract`` and
  ``graphLifecycleContract.json``; for each promoted role whose prompt_text differs
  from its skill INSTRUCTIONS it contains ``src/core/skills/<role>.py``.  A no-op
  promote prints neither ``--write-contract`` nor ``src/core/skills/``.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import src.core.database  # noqa: F401

from evals.harness import config
from evals.harness import promote
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    GraphV1Manifest,
    definition_content_hash,
    load_graph_v1_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_REL = "src/services/agent_definition_manifest_v1.py"
LOADER_PIN_REL = "tests/unit/test_packaged_release_loader.py"
MANIFEST_PIN_REL = "tests/unit/test_graph_definition_manifest.py"
TARGETS = (MANIFEST_REL, LOADER_PIN_REL, MANIFEST_PIN_REL)
PIN_FILES = (LOADER_PIN_REL, MANIFEST_PIN_REL)
HEADER = '"""Generated Graph Version 1 Agent Definition snapshot. Do not edit by hand."""\n\n'

NEW_ENDPOINT = "databricks-claude-sonnet-4-5"
NEW_MAX_TOKENS = 4096


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _protect_real_files():
    """Snapshot the real artefacts; restore them and fail if any test touched them."""
    snapshot = {rel: (REPO_ROOT / rel).read_bytes() for rel in TARGETS}
    yield
    leaked = [rel for rel in TARGETS if (REPO_ROOT / rel).read_bytes() != snapshot[rel]]
    for rel in leaked:
        (REPO_ROOT / rel).write_bytes(snapshot[rel])
    assert not leaked, f"test wrote the REAL artefacts (restored): {leaked}"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A tmp repo tree holding copies of the three targets (and the skill bodies)."""
    for rel in TARGETS:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, dst)
    shutil.copytree(REPO_ROOT / "src/core/skills", tmp_path / "src/core/skills")
    return tmp_path


def _read_all(root: Path) -> dict[str, bytes]:
    return {rel: (root / rel).read_bytes() for rel in TARGETS}


def _manifest_json(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "GRAPH_VERSION_1_MANIFEST_JSON"
            for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("GRAPH_VERSION_1_MANIFEST_JSON not found")


def _defs_by_key(manifest_json: str) -> dict[str, dict]:
    return {d["agent_key"]: d for d in json.loads(manifest_json)["definitions"]}


def _current_hashes() -> dict[str, str]:
    return {
        d.agent_key: definition_content_hash(d) for d in load_graph_v1_manifest().definitions
    }


def _changed(agent_key: str, *, prompt_suffix: str | None = None, **model_updates):
    """A correctly-hashed config derived from the v1 baseline."""
    base = config.v1_baseline(agent_key)
    content = base.content
    if model_updates:
        content = content.model_copy(update={"model": content.model.model_copy(update=model_updates)})
    if prompt_suffix is not None:
        content = content.model_copy(update={"prompt_text": content.prompt_text + prompt_suffix})
    return config.AgentEvalConfig(agent_key, "candidate", content, definition_content_hash(content))


def _expected_manifest_file(original_text: str, edits: dict[str, dict]) -> str:
    """Apply in-place field edits to the parsed JSON and serialise as the frozen file does."""
    j = _manifest_json_from_text(original_text)
    parsed = json.loads(j)
    for d in parsed["definitions"]:
        for field, value in edits.get(d["agent_key"], {}).items():
            if field == "prompt_text":
                d["prompt_text"] = value
            else:
                d["model"][field] = value
    new_j = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
    return HEADER + "GRAPH_VERSION_1_MANIFEST_JSON = " + repr(new_j) + "\n"


def _manifest_json_from_text(text: str) -> str:
    module = ast.parse(text)
    for node in module.body:
        if isinstance(node, ast.Assign):
            return ast.literal_eval(node.value)
    raise AssertionError("no assignment")


def _expected_pin_file(original_text: str, role: str, old: str, new: str) -> str:
    old_line = f'"{role}": "{old}"'
    assert original_text.count(old_line) == 1
    return original_text.replace(old_line, f'"{role}": "{new}"')


def _pinned_table(path: Path) -> dict[str, str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PACKAGED_V1_CONTENT_HASHES" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"PACKAGED_V1_CONTENT_HASHES not found in {path}")


def _assert_single_role_change(tree: Path, before: dict[str, bytes], role: str, cfg, edits, result):
    """Byte-exact expectation for a single-role promote."""
    old_hashes = _current_hashes()
    new_hash = cfg.content_hash

    # manifest: byte-exact against the frozen serialisation rule
    new_manifest_text = (tree / MANIFEST_REL).read_text(encoding="utf-8")
    assert new_manifest_text == _expected_manifest_file(
        before[MANIFEST_REL].decode("utf-8"), {role: edits}
    )

    # manifest: semantically, only that role and only those fields changed
    old_defs = _defs_by_key(_manifest_json_from_text(before[MANIFEST_REL].decode("utf-8")))
    new_defs = _defs_by_key(_manifest_json(tree / MANIFEST_REL))
    assert list(new_defs) == list(GRAPH_V1_AGENT_KEYS)
    for key in GRAPH_V1_AGENT_KEYS:
        if key != role:
            assert new_defs[key] == old_defs[key], key
    patched = json.loads(json.dumps(old_defs[role]))
    for field, value in edits.items():
        if field == "prompt_text":
            patched["prompt_text"] = value
        else:
            patched["model"][field] = value
    assert new_defs[role] == patched
    assert new_defs[role] != old_defs[role]

    # the new manifest validates and holds exactly the evaluated content
    manifest = GraphV1Manifest.model_validate_json(_manifest_json(tree / MANIFEST_REL))
    manifest.assert_complete(GRAPH_V1_AGENT_KEYS)
    by_key = {d.agent_key: d for d in manifest.definitions}
    assert definition_content_hash(by_key[role]) == new_hash
    assert by_key[role] == cfg.content
    assert new_hash != old_hashes[role]
    for key in GRAPH_V1_AGENT_KEYS:
        if key != role:
            assert definition_content_hash(by_key[key]) == old_hashes[key]

    # pin files: byte-exact (only the one entry changed; schema digests untouched)
    for rel in PIN_FILES:
        text = (tree / rel).read_text(encoding="utf-8")
        assert text == _expected_pin_file(
            before[rel].decode("utf-8"), role, old_hashes[role], new_hash
        ), rel
        table = _pinned_table(tree / rel)
        assert table[role] == new_hash
        for key in GRAPH_V1_AGENT_KEYS:
            if key != role:
                assert table[key] == old_hashes[key]

    # schema-contract digest blocks are untouched
    def _block(text: str, name: str) -> str:
        start = text.index(f"{name} = {{")
        return text[start : text.index("}", start)]

    for name in ("V1_SCHEMA_CONTRACT_DIGESTS", "V2_SCHEMA_CONTRACT_DIGESTS"):
        assert _block((tree / MANIFEST_PIN_REL).read_text(encoding="utf-8"), name) == _block(
            before[MANIFEST_PIN_REL].decode("utf-8"), name
        )

    # return value: all seven roles -> final hashes
    expected = dict(old_hashes)
    expected[role] = new_hash
    assert result == expected


# ---------------------------------------------------------------------------
# Brief Step 1 tests
# ---------------------------------------------------------------------------


def test_promoting_v1_to_itself_is_a_no_op(tree):
    before = _read_all(tree)
    result = promote.promote({}, dry_run=True, repo_root=tree)
    assert result == _current_hashes()
    assert _read_all(tree) == before


def test_dry_run_with_default_repo_root_reads_the_real_repo_and_writes_nothing():
    import src.services.agent_definition_manifest_v1 as m

    before = open(m.__file__, "rb").read()
    result = promote.promote({}, dry_run=True)
    assert result == _current_hashes()
    assert open(m.__file__, "rb").read() == before


def test_changing_data_analyst_prompt_is_blocked_by_default(tree):
    cfg = config.v1_baseline("data_analyst")
    changed = config.AgentEvalConfig(
        "data_analyst",
        "x",
        cfg.content.model_copy(update={"prompt_text": cfg.content.prompt_text + "\n\nEXTRA"}),
        "ignored",
    )
    before = _read_all(tree)
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({"data_analyst": changed}, repo_root=tree)
    assert "data_analyst" in str(e.value)
    assert _read_all(tree) == before


def test_promote_blocked_is_a_runtime_error():
    assert issubclass(promote.PromoteBlocked, RuntimeError)


# ---------------------------------------------------------------------------
# promote-to-self byte identity
# ---------------------------------------------------------------------------


def test_non_dry_promote_of_empty_choice_is_byte_identical(tree, capsys):
    before = _read_all(tree)
    result = promote.promote({}, repo_root=tree)
    assert _read_all(tree) == before
    assert result == _current_hashes()
    out = capsys.readouterr().out
    assert "--write-contract" not in out
    assert "src/core/skills/" not in out


def test_non_dry_promote_of_all_seven_baselines_is_byte_identical(tree, capsys):
    before = _read_all(tree)
    chosen = {key: config.v1_baseline(key) for key in GRAPH_V1_AGENT_KEYS}
    result = promote.promote(chosen, repo_root=tree)
    assert _read_all(tree) == before
    assert result == _current_hashes()
    assert set(result) == set(GRAPH_V1_AGENT_KEYS)
    out = capsys.readouterr().out
    assert "--write-contract" not in out
    assert "src/core/skills/" not in out


# ---------------------------------------------------------------------------
# real changes
# ---------------------------------------------------------------------------


def test_builder_endpoint_and_max_tokens_change_only_that_definition_and_hash(tree, capsys):
    before = _read_all(tree)
    cfg = _changed("builder", endpoint_name=NEW_ENDPOINT, max_tokens=NEW_MAX_TOKENS)
    result = promote.promote({"builder": cfg}, repo_root=tree)
    _assert_single_role_change(
        tree,
        before,
        "builder",
        cfg,
        {"endpoint_name": NEW_ENDPOINT, "max_tokens": NEW_MAX_TOKENS},
        result,
    )
    out = capsys.readouterr().out
    assert "--write-contract" in out
    assert "graphLifecycleContract.json" in out
    # prompt unchanged -> skill body still in sync -> no drift reminder
    assert "src/core/skills/" not in out


def test_builder_prompt_change_changes_only_prompt_and_hash(tree, capsys):
    before = _read_all(tree)
    suffix = "\n\nAlways cite the data source on every chart — “quoted”."
    cfg = _changed("builder", prompt_suffix=suffix)
    result = promote.promote({"builder": cfg}, repo_root=tree)
    _assert_single_role_change(
        tree, before, "builder", cfg, {"prompt_text": cfg.content.prompt_text}, result
    )
    out = capsys.readouterr().out
    assert "--write-contract" in out
    assert "graphLifecycleContract.json" in out
    assert "src/core/skills/builder.py" in out
    for key in GRAPH_V1_AGENT_KEYS:
        if key != "builder":
            assert f"src/core/skills/{key}.py" not in out


def test_dry_run_of_a_real_change_returns_new_hash_and_writes_nothing(tree, capsys):
    before = _read_all(tree)
    cfg = _changed("builder", endpoint_name=NEW_ENDPOINT, max_tokens=NEW_MAX_TOKENS)
    result = promote.promote({"builder": cfg}, dry_run=True, repo_root=tree)
    expected = _current_hashes()
    expected["builder"] = cfg.content_hash
    assert result == expected
    assert _read_all(tree) == before


def test_promote_is_idempotent_on_its_own_output(tree):
    cfg = _changed("builder", endpoint_name=NEW_ENDPOINT, max_tokens=NEW_MAX_TOKENS)
    first = promote.promote({"builder": cfg}, repo_root=tree)
    after_first = _read_all(tree)
    second = promote.promote({"builder": cfg}, repo_root=tree)
    assert second == first
    assert _read_all(tree) == after_first


def test_pin_replacement_is_scoped_to_the_packaged_hashes_block(tree):
    """The old hash appearing OUTSIDE the PACKAGED_V1_CONTENT_HASHES block is left alone."""
    old = _current_hashes()["builder"]
    decoy = f'\n\n# decoy outside the pinned block: "builder": "{old}"\n'
    for rel in PIN_FILES:
        with open(tree / rel, "a", encoding="utf-8") as f:
            f.write(decoy)
    before = _read_all(tree)
    cfg = _changed("builder", endpoint_name=NEW_ENDPOINT, max_tokens=NEW_MAX_TOKENS)
    promote.promote({"builder": cfg}, repo_root=tree)
    for rel in PIN_FILES:
        text = (tree / rel).read_text(encoding="utf-8")
        assert text.endswith(decoy), rel
        assert _pinned_table(tree / rel)["builder"] == cfg.content_hash
        original = before[rel].decode("utf-8")
        head = original[: -len(decoy)]
        assert text == _expected_pin_file(head, "builder", old, cfg.content_hash) + decoy


# ---------------------------------------------------------------------------
# transition lock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["build_reviewer", "data_analyst"])
def test_transition_locked_prompt_change_is_blocked_and_writes_nothing(tree, role, capsys):
    before = _read_all(tree)
    cfg = _changed(role, prompt_suffix="\n\nEXTRA RULE.")  # correctly hashed
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({role: cfg}, repo_root=tree)
    assert role in str(e.value)
    assert "prompt" in str(e.value).lower()
    assert _read_all(tree) == before
    assert "--write-contract" not in capsys.readouterr().out


def test_transition_locked_prompt_change_is_blocked_even_in_dry_run(tree):
    cfg = _changed("build_reviewer", prompt_suffix="\n\nEXTRA RULE.")
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({"build_reviewer": cfg}, dry_run=True, repo_root=tree)
    assert "build_reviewer" in str(e.value)


def test_build_reviewer_endpoint_only_change_is_allowed(tree, capsys):
    before = _read_all(tree)
    cfg = _changed("build_reviewer", endpoint_name=NEW_ENDPOINT)
    result = promote.promote({"build_reviewer": cfg}, repo_root=tree)
    _assert_single_role_change(
        tree, before, "build_reviewer", cfg, {"endpoint_name": NEW_ENDPOINT}, result
    )
    out = capsys.readouterr().out
    assert "--write-contract" in out
    assert "src/core/skills/" not in out


# ---------------------------------------------------------------------------
# fail-closed guards + atomicity
# ---------------------------------------------------------------------------


def test_content_hash_mismatch_is_refused_and_writes_nothing(tree):
    before = _read_all(tree)
    good = _changed("builder", endpoint_name=NEW_ENDPOINT, max_tokens=NEW_MAX_TOKENS)
    stale_hash = _current_hashes()["builder"]  # the hash of the UNCHANGED builder
    bad = config.AgentEvalConfig("builder", "lying", good.content, stale_hash)
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({"builder": bad}, repo_root=tree)
    assert "builder" in str(e.value)
    assert _read_all(tree) == before


def test_content_hash_mismatch_on_unchanged_content_is_refused(tree):
    before = _read_all(tree)
    base = config.v1_baseline("fixer")
    bad = config.AgentEvalConfig("fixer", "lying", base.content, "0" * 64)
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({"fixer": bad}, repo_root=tree)
    assert "fixer" in str(e.value)
    assert _read_all(tree) == before


def test_unknown_role_key_is_refused_and_writes_nothing(tree):
    before = _read_all(tree)
    base = config.v1_baseline("builder")
    wizard = config.AgentEvalConfig("wizard", "x", base.content, base.content_hash)
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote(
            {"builder": _changed("builder", endpoint_name=NEW_ENDPOINT), "wizard": wizard},
            repo_root=tree,
        )
    assert "wizard" in str(e.value)
    assert _read_all(tree) == before


def test_chosen_key_not_matching_config_agent_key_is_refused(tree):
    before = _read_all(tree)
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({"builder": config.v1_baseline("fixer")}, repo_root=tree)
    assert "builder" in str(e.value)
    assert _read_all(tree) == before


def test_mixed_valid_and_blocked_roles_writes_nothing(tree):
    """A valid builder change alongside a locked change must not partially apply."""
    before = _read_all(tree)
    chosen = {
        "builder": _changed("builder", endpoint_name=NEW_ENDPOINT, max_tokens=NEW_MAX_TOKENS),
        "build_reviewer": _changed("build_reviewer", prompt_suffix="\n\nEXTRA."),
    }
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote(chosen, repo_root=tree)
    assert "build_reviewer" in str(e.value)
    assert _read_all(tree) == before


@pytest.mark.parametrize("tampered", PIN_FILES)
@pytest.mark.parametrize("mode", ["missing", "duplicated"])
def test_pin_entry_not_found_exactly_once_aborts_after_compute_and_writes_nothing(
    tree, tampered, mode
):
    """A refusal raised AFTER the manifest is computed (at the pin-rewrite step)
    must leave all three files untouched — including the other pin file."""
    old = _current_hashes()["builder"]
    path = tree / tampered
    text = path.read_text(encoding="utf-8")
    line = f'    "builder": "{old}",\n'
    assert text.count(line) == 1
    if mode == "missing":
        text = text.replace(line, f'    "builder": "{"f" * 64}",\n')
    else:
        text = text.replace(line, line + line)
    path.write_text(text, encoding="utf-8")
    before = _read_all(tree)

    cfg = _changed("builder", endpoint_name=NEW_ENDPOINT, max_tokens=NEW_MAX_TOKENS)
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({"builder": cfg}, repo_root=tree)
    assert "builder" in str(e.value)
    assert _read_all(tree) == before


@pytest.mark.parametrize("role", ["build_reviewer", "data_analyst"])
def test_lock_compares_against_transition_source_not_a_drifted_manifest(tree, role):
    """If the repo_root manifest's locked prompt has drifted from the transition's
    source_composite_prompt (e.g. hand-edited), a config carrying that drifted prompt
    must still be refused: the migration only matches source_composite_prompt."""
    path = tree / MANIFEST_REL
    original = path.read_text(encoding="utf-8")
    drifted_prompt = config.v1_baseline(role).content.prompt_text + "\n\nHAND EDIT."
    path.write_text(_expected_manifest_file(original, {role: {"prompt_text": drifted_prompt}}),
                    encoding="utf-8")
    before = _read_all(tree)
    content = config.v1_baseline(role).content
    content = content.model_copy(update={
        "prompt_text": drifted_prompt,
        "model": content.model.model_copy(update={"endpoint_name": NEW_ENDPOINT}),
    })
    cfg = config.AgentEvalConfig(role, "drifted", content, definition_content_hash(content))
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({role: cfg}, repo_root=tree)
    assert role in str(e.value)
    assert "prompt" in str(e.value).lower()
    assert _read_all(tree) == before


def test_config_change_outside_editable_fields_is_refused_by_manifest_hash_guard(tree):
    """A correctly self-hashed config changing a field promote does not carry
    (definition_version) must fail the manifest-hash == config-hash guard."""
    before = _read_all(tree)
    base = config.v1_baseline("builder").content
    content = base.model_copy(update={"definition_version": base.definition_version + 1})
    cfg = config.AgentEvalConfig("builder", "uncarried", content, definition_content_hash(content))
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({"builder": cfg}, repo_root=tree)
    assert "builder" in str(e.value)
    assert _read_all(tree) == before


# ---------------------------------------------------------------------------
# leak guard — keep LAST
# ---------------------------------------------------------------------------


def test_zz_real_artefacts_unchanged_versus_head():
    for rel in TARGETS:
        head = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        assert (REPO_ROOT / rel).read_bytes() == head, rel
