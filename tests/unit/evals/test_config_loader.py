import pytest
from evals.harness import config

def test_v1_baseline_matches_the_frozen_manifest():
    from src.services.graph_definition_manifest import load_graph_v1_manifest
    man = {d.agent_key: d for d in load_graph_v1_manifest().definitions}
    from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
    for key in GRAPH_V1_AGENT_KEYS:
        cfg = config.v1_baseline(key)
        assert cfg.name == "v1-baseline"
        assert cfg.content == man[key]
        from src.services.graph_definition_manifest import definition_content_hash
        assert cfg.content_hash == definition_content_hash(man[key])

def test_override_endpoint_and_prompt_rebuilds_content(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "agent_key: builder\nname: sonnet-test\n"
        "endpoint_name: databricks-claude-sonnet-5\nmax_tokens: 4096\n"
        "prompt_text: \"You are a slide builder. Build ONE slide.\"\n"
    )
    cfg = config.load_config(p)
    assert cfg.agent_key == "builder"
    assert cfg.content.model.endpoint_name == "databricks-claude-sonnet-5"
    assert cfg.content.model.max_tokens == 4096
    assert cfg.content.prompt_text.startswith("You are a slide builder")
    # hash moved away from baseline
    assert cfg.content_hash != config.v1_baseline("builder").content_hash

def test_unknown_agent_key_is_rejected_by_field_name(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("agent_key: wizard\nname: x\n")
    with pytest.raises(config.ConfigError) as e:
        config.load_config(p)
    assert "agent_key" in str(e.value)
