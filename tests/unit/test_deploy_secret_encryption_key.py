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


import base64
from cryptography.fernet import Fernet
from databricks.sdk.service.workspace import GetSecretResponse


def _secret_ws(value=None, get_error=None):
    ws = MagicMock()
    if get_error:
        ws.secrets.get_secret.side_effect = get_error
    else:
        encoded = base64.b64encode(value.encode()).decode()
        ws.secrets.get_secret.return_value = GetSecretResponse(key="k", value=encoded)
    return ws


def test_read_secret_key_base64_decodes():
    key = Fernet.generate_key().decode()
    ws = _secret_ws(value=key)
    assert secret_key.read_secret_key(ws, "tellr", "k") == key


def test_read_secret_key_returns_none_when_absent():
    ws = _secret_ws(get_error=Exception("RESOURCE_DOES_NOT_EXIST"))
    assert secret_key.read_secret_key(ws, "tellr", "k") is None


def test_read_secret_key_raises_on_permission_denied():
    """A denial must never be mistaken for absence — that would clobber a live key."""
    ws = _secret_ws(get_error=Exception("PERMISSION_DENIED"))
    with pytest.raises(SecretKeyError, match="permission"):
        secret_key.read_secret_key(ws, "tellr", "k")


def test_read_secret_key_rejects_non_fernet_value():
    ws = _secret_ws(value="not-a-fernet-key")
    with pytest.raises(SecretKeyError, match="not a valid Fernet key"):
        secret_key.read_secret_key(ws, "tellr", "k")


def test_write_and_verify_round_trips():
    key = Fernet.generate_key().decode()
    ws = _secret_ws(value=key)
    secret_key.write_and_verify_secret_key(ws, "tellr", "k", key)
    ws.secrets.put_secret.assert_called_once_with(
        scope="tellr", key="k", string_value=key
    )


def test_write_and_verify_aborts_on_mismatch():
    """If the read-back differs, abort before anything irreversible happens."""
    ws = _secret_ws(value=Fernet.generate_key().decode())
    with pytest.raises(SecretKeyError, match="read-back"):
        secret_key.write_and_verify_secret_key(
            ws, "tellr", "k", Fernet.generate_key().decode()
        )


# ---------------------------------------------------------------------------
# Health-gate tests (Task 6)
# ---------------------------------------------------------------------------


def _poll_ws():
    ws = MagicMock()
    ws.config.authenticate.return_value = {"Authorization": "Bearer t"}
    return ws


def _resp(status=200, payload=None, raise_json=False):
    r = MagicMock()
    r.status_code = status
    if raise_json:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = payload or {}
    return r


@pytest.mark.parametrize(
    "response",
    [
        _resp(200, {"encryption_key_source": "lakebase"}),
        _resp(200, {"status": "healthy"}),          # field absent — old app code
        _resp(200, raise_json=True),                 # unparseable body
        _resp(503, {"encryption_key_source": "secret"}),
    ],
    ids=["reports-lakebase", "field-absent", "unparseable", "non-200"],
)
def test_health_gate_fails_closed(monkeypatch, response):
    monkeypatch.setattr(secret_key.requests, "get", lambda *a, **k: response)
    assert secret_key.app_reports_secret_source(
        _poll_ws(), "https://app", attempts=1, delay=0
    ) is False


def test_health_gate_fails_closed_on_timeout(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(secret_key.requests, "get", boom)
    assert secret_key.app_reports_secret_source(
        _poll_ws(), "https://app", attempts=2, delay=0
    ) is False


def test_health_gate_opens_only_on_secret(monkeypatch):
    monkeypatch.setattr(
        secret_key.requests, "get",
        lambda *a, **k: _resp(200, {"encryption_key_source": "secret"}),
    )
    assert secret_key.app_reports_secret_source(
        _poll_ws(), "https://app", attempts=1, delay=0
    ) is True


def test_health_gate_sends_workspace_credentials(monkeypatch):
    seen = {}

    def capture(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _resp(200, {"encryption_key_source": "secret"})

    monkeypatch.setattr(secret_key.requests, "get", capture)
    secret_key.app_reports_secret_source(_poll_ws(), "https://app/", attempts=1, delay=0)
    assert seen["url"] == "https://app/api/health"
    assert seen["headers"]["Authorization"] == "Bearer t"


# ---------------------------------------------------------------------------
# Task 7 tests: build_secret_resource, resolve_key_for_create
# ---------------------------------------------------------------------------


def test_build_secret_resource_shape():
    r = secret_key.build_secret_resource("tellr", "tellr-encryption-key")
    assert r.name == "TELLR_ENCRYPTION_KEY"
    assert r.secret.scope == "tellr"
    assert r.secret.key == "tellr-encryption-key"
    assert r.secret.permission.value.upper() == "READ"


def test_resolve_key_for_create_reuses_existing_secret():
    """An existing secret may already protect ciphertext — never overwrite it."""
    existing = Fernet.generate_key().decode()
    ws = _secret_ws(value=existing)
    assert secret_key.resolve_key_for_create(ws, "tellr", "k") == existing
    ws.secrets.put_secret.assert_not_called()


def test_resolve_key_for_create_generates_when_absent():
    ws = MagicMock()
    ws.secrets.get_secret.side_effect = Exception("RESOURCE_DOES_NOT_EXIST")
    generated = {}

    def capture(scope, key, string_value):
        generated["v"] = string_value
        encoded = base64.b64encode(string_value.encode()).decode()
        ws.secrets.get_secret.side_effect = None
        ws.secrets.get_secret.return_value = GetSecretResponse(key=key, value=encoded)

    ws.secrets.put_secret.side_effect = capture
    result = secret_key.resolve_key_for_create(ws, "tellr", "k")
    assert result == generated["v"]
    assert Fernet(result.encode())


# ---------------------------------------------------------------------------
# Task 8 tests: read_lakebase_key, resolve_key_for_update
# ---------------------------------------------------------------------------


def test_read_lakebase_key_returns_row_value():
    cur = MagicMock()
    cur.fetchone.return_value = ("abc",)
    assert secret_key.read_lakebase_key(cur, "app_data") == "abc"


def test_read_lakebase_key_returns_none_when_table_absent():
    cur = MagicMock()
    cur.execute.side_effect = Exception('relation "app_data.encryption_keys" does not exist')
    assert secret_key.read_lakebase_key(cur, "app_data") is None


def test_read_lakebase_key_fails_closed_on_permission_error():
    """A denied SELECT must abort, never look like 'no row'."""
    cur = MagicMock()
    cur.execute.side_effect = Exception("permission denied for table encryption_keys")
    with pytest.raises(SecretKeyError, match="permission"):
        secret_key.read_lakebase_key(cur, "app_data")


def test_ladder_case1_reuses_matching_secret():
    k = Fernet.generate_key().decode()
    ws = _secret_ws(value=k)
    value, wrote = secret_key.resolve_key_for_update(ws, "s", "k", k, None)
    assert (value, wrote) == (k, False)
    ws.secrets.put_secret.assert_not_called()


def test_ladder_case1_hard_fails_on_mismatch():
    """Reusing a mismatched secret would orphan ciphertext under the other key."""
    ws = _secret_ws(value=Fernet.generate_key().decode())
    with pytest.raises(SecretKeyError, match="different key"):
        secret_key.resolve_key_for_update(
            ws, "s", "k", Fernet.generate_key().decode(), None
        )


def test_ladder_case2_relocates_lakebase_key():
    row_key = Fernet.generate_key().decode()
    ws = MagicMock()
    ws.secrets.get_secret.side_effect = Exception("RESOURCE_DOES_NOT_EXIST")

    def capture(scope, key, string_value):
        ws.secrets.get_secret.side_effect = None
        ws.secrets.get_secret.return_value = GetSecretResponse(
            key=key, value=base64.b64encode(string_value.encode()).decode()
        )

    ws.secrets.put_secret.side_effect = capture
    value, wrote = secret_key.resolve_key_for_update(ws, "s", "k", row_key, None)
    assert (value, wrote) == (row_key, True)


def test_ladder_case3_relocates_app_yaml_key():
    legacy = Fernet.generate_key().decode()
    ws = MagicMock()
    ws.secrets.get_secret.side_effect = Exception("RESOURCE_DOES_NOT_EXIST")

    def capture(scope, key, string_value):
        ws.secrets.get_secret.side_effect = None
        ws.secrets.get_secret.return_value = GetSecretResponse(
            key=key, value=base64.b64encode(string_value.encode()).decode()
        )

    ws.secrets.put_secret.side_effect = capture
    value, wrote = secret_key.resolve_key_for_update(ws, "s", "k", None, legacy)
    assert (value, wrote) == (legacy, True)


def test_ladder_case4_generates_when_nothing_exists():
    ws = MagicMock()
    ws.secrets.get_secret.side_effect = Exception("RESOURCE_DOES_NOT_EXIST")

    def capture(scope, key, string_value):
        ws.secrets.get_secret.side_effect = None
        ws.secrets.get_secret.return_value = GetSecretResponse(
            key=key, value=base64.b64encode(string_value.encode()).decode()
        )

    ws.secrets.put_secret.side_effect = capture
    value, wrote = secret_key.resolve_key_for_update(ws, "s", "k", None, None)
    assert wrote is True
    assert Fernet(value.encode())


# ---------------------------------------------------------------------------
# Task 9 tests: attach_secret_resource, delete_lakebase_key_row
# ---------------------------------------------------------------------------

from databricks.sdk.service.apps import App, ComputeSize


def test_attach_preserves_mutable_fields_and_omits_compute_size():
    """apps.update rejects compute_size and wipes omitted fields (verified live)."""
    ws = MagicMock()
    db_resource = MagicMock()
    db_resource.name = "app_database"
    db_resource.secret = None
    ws.apps.get.return_value = App(
        name="app", description="Tellr", compute_size=ComputeSize.MEDIUM,
        default_source_code_path="/ws/src", user_api_scopes=["sql"],
        resources=[db_resource],
    )
    secret_key.attach_secret_resource(ws, "app", "tellr", "tellr-encryption-key")
    sent = ws.apps.update.call_args.kwargs["app"]
    assert sent.compute_size is None
    assert sent.description == "Tellr"
    assert sent.user_api_scopes == ["sql"]
    assert sent.default_source_code_path == "/ws/src"
    names = [r.name for r in sent.resources]
    assert names == ["app_database", "TELLR_ENCRYPTION_KEY"]


def test_attach_replaces_an_existing_secret_resource():
    ws = MagicMock()
    stale = secret_key.build_secret_resource("old-scope", "old-key")
    ws.apps.get.return_value = App(name="app", resources=[stale])
    secret_key.attach_secret_resource(ws, "app", "new-scope", "new-key")
    sent = ws.apps.update.call_args.kwargs["app"]
    assert len(sent.resources) == 1
    assert sent.resources[0].secret.scope == "new-scope"


def test_delete_lakebase_key_row_issues_the_delete():
    cur = MagicMock()
    secret_key.delete_lakebase_key_row(cur, "app_data")
    sql = cur.execute.call_args[0][0]
    assert "DELETE FROM" in sql and "encryption_keys" in sql and "WHERE id = 1" in sql
