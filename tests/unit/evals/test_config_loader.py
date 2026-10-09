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


# ---- I6: bad config is rejected, naming the field ----

def _load(tmp_path, body):
    p = tmp_path / "c.yaml"
    p.write_text("agent_key: builder\nname: x\n" + body)
    return config.load_config(p)


def test_typod_key_is_rejected_naming_the_key(tmp_path):
    with pytest.raises(config.ConfigError) as e:
        _load(tmp_path, "temprature: 0.2\n")
    assert "temprature" in str(e.value)


def test_base_other_than_v1_is_rejected(tmp_path):
    with pytest.raises(config.ConfigError) as e:
        _load(tmp_path, "base: v2\n")
    assert "base" in str(e.value) and "v2" in str(e.value)


def test_base_v1_is_accepted(tmp_path):
    assert _load(tmp_path, "base: v1\n").content == config.v1_baseline("builder").content


def test_out_of_range_max_tokens_is_rejected_naming_the_field(tmp_path):
    with pytest.raises(config.ConfigError) as e:
        _load(tmp_path, "max_tokens: -5\n")
    assert "max_tokens" in str(e.value)


def test_out_of_range_temperature_is_rejected_naming_the_field(tmp_path):
    with pytest.raises(config.ConfigError) as e:
        _load(tmp_path, "temperature: 9\n")
    assert "temperature" in str(e.value)
