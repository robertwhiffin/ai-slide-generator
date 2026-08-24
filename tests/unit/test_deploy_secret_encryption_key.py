"""Secret-backed Fernet key deploy helpers.

See docs/superpowers/specs/2026-08-20-secret-backed-fernet-key-design.md.
"""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from databricks.sdk.service.workspace import ScopeBackendType, SecretScope
from databricks_tellr import secret_key
from databricks_tellr.secret_key import SecretKeyError


def _ws(scopes=(), create_error=None):
    ws = MagicMock()
    ws.secrets.list_scopes.return_value = list(scopes)
    if create_error:
        ws.secrets.create_scope.side_effect = create_error
    return ws


def test_preflight_accepts_existing_databricks_backed_scope():
    ws = _ws([SecretScope(name="tellr", backend_type=ScopeBackendType.DATABRICKS)])
    secret_key.preflight_scope(ws, "tellr")
    ws.secrets.create_scope.assert_not_called()


def test_preflight_creates_missing_scope_without_initial_manage_principal():
    ws = _ws([])
    secret_key.preflight_scope(ws, "tellr")
    kwargs = ws.secrets.create_scope.call_args.kwargs
    assert kwargs["scope"] == "tellr"
    assert "initial_manage_principal" not in kwargs


def test_preflight_refuses_keyvault_backed_scope():
    ws = _ws([SecretScope(name="tellr", backend_type=ScopeBackendType.AZURE_KEYVAULT)])
    with pytest.raises(SecretKeyError, match="Key Vault"):
        secret_key.preflight_scope(ws, "tellr")


def test_preflight_maps_permission_error_to_actionable_message():
    ws = _ws([], create_error=Exception("CUSTOMER_UNAUTHORIZED: nope"))
    with pytest.raises(SecretKeyError, match="databricks secrets create-scope tellr"):
        secret_key.preflight_scope(ws, "tellr")


def test_preflight_maps_scope_limit_to_actionable_message():
    ws = _ws([], create_error=Exception("RESOURCE_LIMIT_EXCEEDED"))
    with pytest.raises(SecretKeyError, match="secret-scope limit"):
        secret_key.preflight_scope(ws, "tellr")


def test_lakebase_privilege_probe_passes_when_both_granted():
    cur = MagicMock()
    cur.fetchone.side_effect = [(True,), (True,)]
    secret_key.preflight_lakebase_privileges(cur, "app_data_prod")


def test_lakebase_privilege_probe_aborts_when_delete_missing():
    cur = MagicMock()
    cur.fetchone.side_effect = [(True,), (False,)]
    with pytest.raises(SecretKeyError, match="DELETE"):
        secret_key.preflight_lakebase_privileges(cur, "app_data_prod")
