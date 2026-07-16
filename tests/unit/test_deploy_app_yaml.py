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


def test_app_yaml_has_databricks_token():
    """MEDIUM-4 DROPPED: DATABRICKS_TOKEN stays in app.yaml. It is a
    platform-managed short-lived OAuth token reference (valueFrom:
    system.databricks_token), not a hardcoded secret, and MLflow tracing
    reads it from the env — dropping it broke MLflow, so it is retained.
    (CRITICAL-3 still removes GOOGLE_OAUTH_ENCRYPTION_KEY — see the keyless
    test above.)"""
    import tempfile
    from pathlib import Path

    from databricks_tellr import deploy

    with tempfile.TemporaryDirectory() as td:
        deploy._write_app_yaml(Path(td), "lb", "app_data")
        content = (Path(td) / "app.yaml").read_text()
    assert "DATABRICKS_TOKEN" in content
    assert "system.databricks_token" in content
    assert "DATABRICKS_HOST" in content  # still required by create_user_client
