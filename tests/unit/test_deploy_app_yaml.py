import inspect
from pathlib import Path

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr import deploy


def test_write_app_yaml_has_no_use_test_pypi_param():
    sig = inspect.signature(deploy._write_app_yaml)
    assert "use_test_pypi" not in sig.parameters


def test_generated_app_yaml_has_no_custom_index_url(tmp_path: Path):
    deploy._write_app_yaml(
        tmp_path,
        lakebase_name="db-tellr",
        schema_name="devtest_app_data",
        lakebase_result={"type": "provisioned"},
    )
    content = (tmp_path / "app.yaml").read_text()
    assert "--index-url" not in content
    assert "test.pypi.org" not in content
    assert "pip install --upgrade --no-cache-dir -r requirements.txt" in content


def test_write_app_yaml_is_keyless():
    """CRITICAL-3: app.yaml must not carry the Fernet key or accept one."""
    import inspect as _inspect
    import tempfile
    from pathlib import Path

    from databricks_tellr import deploy

    sig = _inspect.signature(deploy._write_app_yaml)
    assert "encryption_key" not in sig.parameters

    with tempfile.TemporaryDirectory() as td:
        deploy._write_app_yaml(Path(td), "lb", "app_data")
        content = (Path(td) / "app.yaml").read_text()
    assert "GOOGLE_OAUTH_ENCRYPTION_KEY" not in content


def test_app_yaml_has_no_databricks_token():
    """SDR-4437 F-CR-18: SP auth is platform OAuth M2M, not a token env var.

    This assertion was added and reverted once before (a2676e944 -> 6f23a2bef,
    July 2026) on the belief that MLflow tracing needs DATABRICKS_TOKEN in the
    environment. Measured on a live deployment (0.4.3.dev18, 2026-09-08)
    before re-landing it:

    * The deployed app.yaml did carry ``valueFrom: system.databricks_token``,
      yet the SDK resolved ``auth_type=oauth-m2m``. ``pat_auth`` is FIRST in
      the DefaultCredentials chain and needs only host+token, so it can only
      have been skipped because the variable was absent or empty — the
      ``system.databricks_token`` reference does not populate.
    * ``oauth-m2m`` is declared as requiring host+client_id+client_secret, so
      its selection proves DATABRICKS_CLIENT_SECRET *is* injected; the
      subsequent ``current_user.me()`` call then succeeded.
    * MLflow needs no token of its own — it delegates to this same SDK chain
      whenever MLFLOW_ENABLE_DB_SDK is set, which is its default.

    So the entry was inert config, and removing it cannot change runtime
    behaviour: the app already authenticates without it. Before reverting this
    again, re-measure ``resolved_auth_type`` on a live deployment rather than
    assuming the July conclusion still holds.

    (CRITICAL-3 still removes GOOGLE_OAUTH_ENCRYPTION_KEY — see the keyless
    test above.)
    """
    import tempfile
    from pathlib import Path

    import yaml

    from databricks_tellr import deploy

    with tempfile.TemporaryDirectory() as td:
        deploy._write_app_yaml(Path(td), "lb", "app_data")
        content = (Path(td) / "app.yaml").read_text()

    # Assert on the parsed env entries, not on substrings: the template carries
    # a comment naming DATABRICKS_TOKEN to warn against reinstating it, and a
    # substring check would flag that comment as the very thing it prevents.
    env = yaml.safe_load(content)["env"]
    names = {entry["name"] for entry in env}
    value_froms = {entry.get("valueFrom") for entry in env}

    assert "DATABRICKS_TOKEN" not in names
    assert "system.databricks_token" not in value_froms
    assert "DATABRICKS_HOST" in names  # still required by create_user_client


def test_app_yaml_omits_secret_block_in_legacy_mode(tmp_path: Path):
    """Legacy deploys must not reference a resource the app does not have."""
    deploy._write_app_yaml(
        tmp_path, lakebase_name="db-tellr", schema_name="app_data",
        lakebase_result={"type": "provisioned"},
    )
    content = (tmp_path / "app.yaml").read_text()
    assert "TELLR_ENCRYPTION_KEY" not in content
    assert "valueFrom" in content  # system.databricks_host etc. still present


def test_app_yaml_includes_secret_block_in_secret_mode(tmp_path: Path):
    deploy._write_app_yaml(
        tmp_path, lakebase_name="db-tellr", schema_name="app_data",
        lakebase_result={"type": "provisioned"},
        encryption_secret_resource_key="TELLR_ENCRYPTION_KEY",
    )
    content = (tmp_path / "app.yaml").read_text()
    assert "- name: TELLR_ENCRYPTION_KEY" in content
    assert 'valueFrom: "TELLR_ENCRYPTION_KEY"' in content


def test_app_yaml_never_contains_key_material(tmp_path: Path):
    """Secret mode references the resource; it must not embed a key."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    deploy._write_app_yaml(
        tmp_path, lakebase_name="db-tellr", schema_name="app_data",
        lakebase_result={"type": "provisioned"},
        encryption_secret_resource_key="TELLR_ENCRYPTION_KEY",
    )
    content = (tmp_path / "app.yaml").read_text()
    assert key not in content
    assert "GOOGLE_OAUTH_ENCRYPTION_KEY" not in content
