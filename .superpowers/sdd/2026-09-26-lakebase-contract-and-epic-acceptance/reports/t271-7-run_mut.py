import os, subprocess, sys
SHA = "fb5d40caa"
TREE = os.path.dirname(os.path.abspath(__file__))
TEST = "tests/integration/test_graph_lifecycle_runtime_postgres.py"
M = {
 "M1": ("src/services/agent_runtime_identity.py", '_LOGGED_IDENTITY_FIELDS = (\n    "graph_version",\n', '_LOGGED_IDENTITY_FIELDS = (\n'),
 "M2": ("src/services/agent_runtime.py", "    structured_model = model.with_structured_output(schema)\n", "    model.bind_tools([])  # T271M2\n    structured_model = model.with_structured_output(schema)\n"),
 "M3": ("src/services/graph/builder.py", '    state: Dict[str, Any] = dict(initial or {})\n    state.update(\n        {\n            "session_id": session_id,\n            "graph_release_id": graph_release_id,\n', '    state: Dict[str, Any] = dict(initial or {})\n    state.update(\n        {\n            "session_id": session_id,\n            "graph_release_id": (initial or {}).get("graph_release_id", graph_release_id),  # T271M3\n'),
 "M4": ("src/services/graph/routers.py", '                "graph_release_id": state["graph_release_id"],\n                "root_session_id": state.get("root_session_id") or "",\n', '                "graph_release_id": record.get("graph_release_id", -7),  # T271M4\n                "root_session_id": state.get("root_session_id") or "",\n'),
 "M5": ("src/services/agent_runtime_identity.py", '                "outcome": "success",\n                "error_class": None,\n', '                "outcome": "success",\n                "error_class": None,\n                "actor": identity.actor_session_id,  # T271M5\n'),
 "M6": ("src/services/agent_runtime_identity.py", '"additional_field_names": sorted(result.additional_fields),', '"additional_field_names": [repr(dict(result.additional_fields))] if result.additional_fields else [],  # T271M6'),
 "M7": ("src/services/graph/nodes.py", '        "message": state.get("architect_message"),\n        "current_deck_spec": persisted_spec_dict,\n', '        "message": state.get("architect_message"),\n        "conversation_ref": session_id,  # T271M7\n        "current_deck_spec": persisted_spec_dict,\n'),
 "M8": ("src/services/persisted_graph_release.py", "                graph_version=release.version_number,\n", "                graph_version=release.id,  # T271M8\n"),
 "M9": ("src/services/prompt_assembler.py", "    return {v1.identity_key: v1, v2.identity_key: v2}\n", "    return {v1.identity_key: v1}  # T271M9\n"),
 "M10": ("src/services/agent_schema_registry.py", "            optional_fields=(() if version == 1 else (_V2_OPTIONAL_DESCRIPTORS[role],)),\n", "            optional_fields=(() if version == 1 else (_V2_OPTIONAL_DESCRIPTORS[role],)) if role != 'builder' else (),  # T271M10\n"),
 "M11": ("src/services/graph/nodes.py", '        "message": state.get("architect_message"),\n        "current_deck_spec": persisted_spec_dict,\n', '        "message": state.get("architect_message"),\n        "initiated_by": state.get("initiated_by"),  # T271M11\n        "current_deck_spec": persisted_spec_dict,\n'),
 "M4b": ("src/services/graph/nodes.py", '        "session_id": state["session_id"],\n        "graph_release_id": state["graph_release_id"],\n        "turn_id": state["turn_id"],\n', '        "session_id": state["session_id"],\n        "graph_release_id": 1,  # T271M4b\n        "turn_id": state["turn_id"],\n'),
 "M9b": ("src/services/agent_runtime.py", "        return self._run_resolved(definition, payload, assembly_context)\n", "        self._prompt_assembler._bundles = {k: v for k, v in self._prompt_assembler._bundles.items() if k[0] != 2}  # T271M9b\n        return self._run_resolved(definition, payload, assembly_context)\n"),
 "M10b": ("src/services/agent_runtime.py", "                    schema=composed.model,\n", "                    schema=composed.model if _observation is not None else composed.canonical_model,  # T271M10b\n"),
 "CI": (".github/workflows/test.yml", "            tests/integration/test_graph_lifecycle_runtime_postgres.py \\\n", ""),
}
env = dict(os.environ, PYTHONPATH=f"{TREE}:{TREE}/packages/databricks-tellr", DATABASE_URL="sqlite:////tmp/t271-7m.sqlite", TELLR_TEST_POSTGRES_URL="postgresql+psycopg2://localhost:5432/postgres")
for name in sys.argv[1:]:
    path, old, new = M[name]
    full = os.path.join(TREE, path)
    src = open(full).read()
    assert src.count(old) == 1, (name, src.count(old))
    open(full, "w").write(src.replace(old, new))
    if new: assert "T271" in new or name == "M1"
    test = "tests/unit/test_ci_collects_integration_tests.py" if name == "CI" else TEST
    try:
        out = subprocess.run(["timeout", "600", "/Users/robert.whiffin/.pyenv/shims/python", "-m", "pytest", test, "-q", "-p", "no:cacheprovider", "--tb=short", "-rs"], cwd=TREE, env=env, capture_output=True, text=True).stdout
    finally:
        subprocess.run(["git", "checkout", SHA, "--", path], cwd=TREE, check=True)
        assert subprocess.run(["git", "diff", "--quiet", SHA, "--", path], cwd=TREE).returncode == 0
    lines = out.splitlines()
    firstE = [l for l in lines if l.startswith("E ")][:2]
    summary = lines[-1] if lines else ""
    failed = [l for l in lines if l.startswith("FAILED")]
    labels = [l.split("StageFailure: ",1)[1][:160] for l in lines if "StageFailure: [" in l or l.startswith("____")] if False else [ (l[:90] if l.startswith("____") else l.split("StageFailure: ",1)[1][:170]) for l in lines if l.startswith("____") or "StageFailure: [" in l]
    print("  labels:", labels)
    print(f"== {name} {path}\n  summary: {summary}\n  failed: {failed}\n  first E: {[l[:400] for l in firstE]}", flush=True)
