"""MEDIUM-5 (SDR-4437): identifiers interpolated into Lakebase DDL are validated."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr.identifiers import validate_client_id, validate_schema_name

VALID_UUID = "12345678-abcd-ABCD-0123-456789abcdef"


class TestValidateSchemaName:
    @pytest.mark.parametrize("name", ["app_data_prod", "_x", "Schema1", "a"])
    def test_valid(self, name):
        assert validate_schema_name(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "", "1abc", "app-data", 'x"; DROP SCHEMA public CASCADE; --',
            'a"b', "a b", "sch;ma", "app_dataé", None,
        ],
    )
    def test_invalid(self, name):
        with pytest.raises(ValueError, match="schema"):
            validate_schema_name(name)


class TestValidateClientId:
    def test_valid_uuid(self):
        assert validate_client_id(VALID_UUID) == VALID_UUID

    def test_valid_numeric_sp_id_fallback(self):
        # _get_app_client_id falls back to str(service_principal_id)
        assert validate_client_id("1234567890") == "1234567890"

    @pytest.mark.parametrize(
        "cid",
        [
            "", "not-a-uuid", VALID_UUID + "x", '"; GRANT ALL --',
            "12345678-abcd-ABCD-0123-456789abcde", None,
        ],
    )
    def test_invalid(self, cid):
        with pytest.raises(ValueError, match="client"):
            validate_client_id(cid)


class TestDeploySitesValidate:
    """The three deploy.py DDL sites reject bad identifiers BEFORE any execute."""

    def test_grant_schema_permissions_rejects_bad_schema(self):
        from databricks_tellr.deploy import _grant_schema_permissions

        cur = MagicMock()
        with pytest.raises(ValueError):
            _grant_schema_permissions(cur, 'x"; DROP SCHEMA y; --', VALID_UUID)
        cur.execute.assert_not_called()

    def test_grant_schema_permissions_rejects_bad_client_id(self):
        from databricks_tellr.deploy import _grant_schema_permissions

        cur = MagicMock()
        with pytest.raises(ValueError):
            _grant_schema_permissions(cur, "app_data", '"; GRANT ALL --')
        cur.execute.assert_not_called()
