from types import SimpleNamespace
from unittest.mock import Mock

from src.services.identity_provider import _resolve_cached
from src.services.identity_providers.account_provider import AccountIdentityProvider
from src.services.identity_providers.scim_filter import escape_scim_filter_string
from src.services.identity_providers.workspace_provider import WorkspaceIdentityProvider

INJECTION_PAYLOAD = 'x" or userName pr "'
ESCAPED_PAYLOAD = 'x\\" or userName pr \\"'


def test_escape_scim_filter_string_escapes_backslashes_before_quotes():
    assert escape_scim_filter_string('path\\name"') == 'path\\\\name\\"'
    assert escape_scim_filter_string(INJECTION_PAYLOAD) == ESCAPED_PAYLOAD


def test_account_search_escapes_query_in_user_and_group_filters():
    provider = AccountIdentityProvider("accounts.example.com", "account-id", "token")
    provider.list_users = Mock(return_value=[])
    provider.list_groups = Mock(return_value=[])

    provider.search_identities(INJECTION_PAYLOAD)

    user_filter = provider.list_users.call_args.kwargs["filter_query"]
    group_filter = provider.list_groups.call_args.kwargs["filter_query"]
    assert user_filter == (f'userName co "{ESCAPED_PAYLOAD}" or displayName co "{ESCAPED_PAYLOAD}"')
    assert group_filter == f'displayName co "{ESCAPED_PAYLOAD}"'
    assert 'co "x" or userName pr "' not in user_filter
    assert 'co "x" or userName pr "' not in group_filter


def test_workspace_lists_escape_query_in_user_and_group_filters():
    client = SimpleNamespace(
        users=SimpleNamespace(list=Mock(return_value=[])),
        groups=SimpleNamespace(list=Mock(return_value=[])),
    )
    provider = WorkspaceIdentityProvider(client)

    provider.list_users(INJECTION_PAYLOAD)
    provider.list_groups(INJECTION_PAYLOAD)

    user_filter = client.users.list.call_args.kwargs["filter"]
    group_filter = client.groups.list.call_args.kwargs["filter"]
    assert user_filter == (f'userName co "{ESCAPED_PAYLOAD}" or displayName co "{ESCAPED_PAYLOAD}"')
    assert group_filter == f'displayName co "{ESCAPED_PAYLOAD}"'
    assert 'co "x" or userName pr "' not in user_filter
    assert 'co "x" or userName pr "' not in group_filter


def test_display_name_resolution_escapes_email_filter(monkeypatch):
    users = SimpleNamespace(list=Mock(return_value=[]))
    workspace_provider = WorkspaceIdentityProvider(SimpleNamespace(users=users))
    provider = SimpleNamespace(_provider=workspace_provider)
    monkeypatch.setattr("src.services.identity_provider.get_identity_provider", lambda: provider)
    _resolve_cached.cache_clear()

    assert _resolve_cached(INJECTION_PAYLOAD) == INJECTION_PAYLOAD

    built_filter = users.list.call_args.kwargs["filter"]
    assert built_filter == f'userName eq "{ESCAPED_PAYLOAD}"'
    assert 'eq "x" or userName pr "' not in built_filter
    _resolve_cached.cache_clear()
