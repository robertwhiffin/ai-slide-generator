"""deploy_local secret-mode plumbing."""

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from scripts import deploy_local


def test_parser_accepts_the_secret_flags():
    parser = deploy_local.build_parser()
    args = parser.parse_args([
        "--update", "--env", "devtest",
        "--encryption-secret-scope", "tellr",
        "--encryption-secret-key", "tellr-encryption-key",
    ])
    assert args.encryption_secret_scope == "tellr"
    assert args.encryption_secret_key == "tellr-encryption-key"


def test_config_surfaces_the_secret_keys(tmp_path, monkeypatch):
    cfg = tmp_path / "deployment.yaml"
    cfg.write_text(
        "environments:\n"
        "  devtest:\n"
        "    app_name: db-tellr-devtest\n"
        "    workspace_path: /ws/devtest\n"
        "    encryption_secret_scope: tellr\n"
        "    encryption_secret_key: custom-key\n"
        "    lakebase:\n"
        "      database_name: db-tellr\n"
        "      schema: devtest_app_data\n"
    )
    monkeypatch.setattr(deploy_local, "CONFIG_PATH", cfg)
    out = deploy_local.load_deployment_config("devtest")
    assert out["encryption_secret_scope"] == "tellr"
    assert out["encryption_secret_key"] == "custom-key"


def test_branch_source_config_exposes_the_source_app_name(tmp_path, monkeypatch):
    """The fork needs the source app's name to read its resources; the
    workspace_path carries no recoverable suffix rule."""
    cfg = tmp_path / "deployment.yaml"
    cfg.write_text(
        "environments:\n"
        "  production:\n"
        "    app_name: db-tellr-prod\n"
        "    workspace_path: /ws/prod/tellr\n"
        "    lakebase:\n"
        "      database_name: db-tellr\n"
        "      schema: app_data_prod\n"
    )
    monkeypatch.setattr(deploy_local, "CONFIG_PATH", cfg)
    src = deploy_local._load_branch_source_config("production")
    assert src["app_name"] == "db-tellr-prod"
