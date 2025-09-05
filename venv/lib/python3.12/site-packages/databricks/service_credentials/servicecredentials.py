#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2025-present Databricks, Inc.
# All Rights Reserved.
#
# NOTICE:  All information contained herein is, and remains the property of Databricks, Inc.
# and its suppliers, if any.  The intellectual and technical concepts contained herein are
# proprietary to Databricks, Inc. and its suppliers and may be covered by U.S. and foreign Patents,
# patents in process, and are protected by trade secret and/or copyright law. Dissemination, use,
# or reproduction of this information is strictly forbidden unless prior written permission is
# obtained from Databricks, Inc.
#
# If you view or obtain a copy of this information and believe Databricks, Inc. may not have
# intended it to be made available, please promptly report it to Databricks Legal Department
# @ legal@databricks.com.
#

import os
from pyspark import TaskContext
from pyspark.databricks.utils.PostImportHook import when_imported
from sys import stderr
from databricks.service_credentials.credential_retriever import CredentialRetriever
from typing import Any


def patch_default_credential_chains():
    @when_imported("botocore.session")
    def hook_botocore_session(botocore_session):
        try:
            if hasattr(botocore_session.get_session, "_db_udf_patched"):
                return
            org_get_session = botocore_session.get_session

            # Patch botocore get_session function to inject service credentials provider.

            def db_get_session(*args, **kwargs):
                bc_session = org_get_session(*args, **kwargs)
                return getAWSDBServiceCredentialsProvider(
                    None, bc_session
                )  # None is used to get the default credential in credential_retriever

            db_get_session._db_udf_patched = True  # type: ignore[attr-defined]
            botocore_session.get_session = db_get_session
        except Exception as e:
            print(
                "Unexpected internal error when monkey patching botocore module: {}".format(
                    e
                ),
                file=stderr,
            )

    @when_imported("azure.identity")
    def hook_azure_identity(azure_identity):
        try:
            if hasattr(
                azure_identity.DefaultAzureCredential.__init__, "_db_udf_patched"
            ):
                return
            org_default_azure_credential_init = (
                azure_identity.DefaultAzureCredential.__init__
            )

            def db_default_azure_credential_init(self, *args, **kwargs):
                org_default_azure_credential_init(self, *args, **kwargs)
                if isinstance(getattr(self, "credentials", None), tuple):
                    # Insert our provider as the first element in the credentials chain
                    self.credentials = (
                        getAzureDBServiceCredentialsProvider(),
                    ) + self.credentials
                else:
                    print(
                        "Failed to patch DefaultAzureCredential: credentials chain not found",
                        file=stderr,
                    )

            db_default_azure_credential_init._db_udf_patched = True  # type: ignore[attr-defined]
            azure_identity.DefaultAzureCredential.__init__ = (
                db_default_azure_credential_init
            )
        except Exception as e:
            print(
                "Unexpected internal error when monkey patching azure.identity module: {}".format(
                    e
                ),
                file=stderr,
            )

    @when_imported("google.auth")
    def hook_gcp_service_account(google_auth):
        try:
            if hasattr(google_auth.default, "_db_udf_patched"):
                return
            org_gcp_auth_default = google_auth.default

            # Replacement version of google.auth.default: returns custom user credentials first if available.
            def db_gcp_auth_default(*args, **kwargs):
                # If default service credential is specified, then we use it with our provider.
                credentials = getGCPDBServiceCredentialsProvider(None)

                # It's ok for 'project_id' to be None. For more details, see google.auth.default() implementation:
                # https://github.com/pydata/pydata-google-auth/blob/main/pydata_google_auth/auth.py
                project_id = os.environ.get(
                    google_auth.environment_vars.PROJECT,
                    os.environ.get(google_auth.environment_vars.LEGACY_PROJECT),
                )

                return credentials, project_id

            db_gcp_auth_default._db_udf_patched = True  # type: ignore[attr-defined]
            google_auth.default = db_gcp_auth_default
        except Exception as e:
            print(
                "Unexpected internal error when monkey patching google.auth module: {}".format(
                    e
                ),
                file=stderr,
            )


def getAWSDBServiceCredentialsProvider(credential_name=None, bc_session=None):
    """Get a boto service credentials provider for the given credential name using CredentialRetriever."""
    import botocore.session
    from botocore.credentials import CredentialProvider, RefreshableCredentials
    from datetime import datetime

    cred_retriever = CredentialRetriever()

    class DBServiceCredentialsProvider(CredentialProvider):
        """An implementation of boto CredentialsProvider loading and refreshing the temporary
        credentials from the Service Credentials UC service. The interface specification is
        defined in https://github.com/boto/botocore/blob/1.34.140/botocore/credentials.py#L940
        """

        METHOD = "databricks-service-credentials"

        def __init__(self, credential_name=None):
            super().__init__()
            self.credential_name = credential_name

        def reload(self):
            aws_credentials = cred_retriever.get_aws_credential(self.credential_name)
            return {
                "token": aws_credentials.session_token,
                "access_key": aws_credentials.access_key_id,
                "secret_key": aws_credentials.secret_access_key,
                "expiry_time": datetime.utcfromtimestamp(
                    aws_credentials.expiration_time_epoch_ms / 1000
                ).strftime("%Y-%m-%d %H:%M:%SZ"),
            }

        def load(self):
            return RefreshableCredentials.create_from_metadata(
                self.reload(), self.reload, self.METHOD
            )

    if bc_session is None:
        bc_session = botocore.session.get_session()

    try:
        cred_provider = bc_session.get_component("credential_provider")
        cred_provider.remove(DBServiceCredentialsProvider.METHOD)  # Remove old provider
        cred_provider.insert_before(
            "env", DBServiceCredentialsProvider(credential_name)
        )  # Add new provider
    except Exception as e:
        print(
            f"Unexpected internal error when setting up AWS service credentials provider: {e}",
            file=stderr,
        )

    return bc_session


def getAzureDBServiceCredentialsProvider(credential_name=None):
    """Get an Azure service credentials provider using CredentialRetriever."""
    from azure.core.credentials import AccessToken, TokenCredential
    from datetime import datetime

    cred_retriever = CredentialRetriever()

    class ServiceCredentialTokenProvider(TokenCredential):
        """An implementation of Azure TokenCredential loading the temporary credentials from
        the Service Credentials UC service. The interface specification is defined in
        https://learn.microsoft.com/en-us/python/api/azure-core/azure.core.credentials.tokencredential
        """

        def __init__(self, credential_name=None):
            super().__init__()
            self.credential_name = credential_name

        def get_token(self, *scopes, **kwargs):
            azure_credentials = cred_retriever.get_azure_credential(
                self.credential_name, scopes
            )
            return AccessToken(
                azure_credentials.aad_token,
                azure_credentials.expiration_time_epoch_ms / 1000,
            )

    return ServiceCredentialTokenProvider(credential_name)


def getGCPDBServiceCredentialsProvider(credential_name=None):
    """Get a GCP service credentials provider using CredentialRetriever."""
    from google.oauth2.credentials import Credentials
    from google.auth.credentials import Scoped
    from functools import partial
    from datetime import datetime

    cred_retriever = CredentialRetriever()

    def service_credentials_refresh(request, scopes, credential_name=None):
        """Refresh handler to fetch new credentials."""
        gcp_credentials = cred_retriever.get_gcp_credential(credential_name, scopes)
        return gcp_credentials.oauth_token, datetime.utcfromtimestamp(
            gcp_credentials.expiration_time_epoch_ms / 1000
        )

    class GCPCustomCredentials(Credentials, Scoped):
        def __init__(self, scopes=None):
            # credentials#refresh_handler only has two arguments, and we bind credential_name as additional arg.
            handler_fn = partial(
                service_credentials_refresh, credential_name=credential_name
            )
            super().__init__(None, scopes=scopes, refresh_handler=handler_fn)

        # The google auth client calls "with_scopes_if_required" when using SA access tokens. The only interface that
        # provides "with_scopes_if_required" is credentials.Scoped. We need to implement "with_scopes", as this is what
        # "Scopes#with_scopes_if_required" calls when "requires_scopes" returns true.
        #
        # For more context, see:
        # - https://github.com/databricks-eng/universe/pull/835750#discussion_r1882307617
        # - https://github.com/googleapis/python-cloud-core/blob/main/google/cloud/client/__init__.py

        def requires_scopes(self):
            return self.scopes is None

        def with_scopes(self, scopes, default_scopes=None):
            return GCPCustomCredentials(scopes=scopes or default_scopes)

    return GCPCustomCredentials()


def getServiceCredentialsProvider(credential_name: str) -> Any:
    """
    Get the credential provider for the specified credential name.
    """
    tc = TaskContext.get()
    if tc is None:
        raise Exception(
            "getServiceCredentialsProvider can only be called in a Python UDF"
        )
    cloud_provider = (
        tc.getLocalProperty("spark.databricks.cloudProvider") or "not_set"
    ).lower()
    if cloud_provider.lower() == "aws":
        return getAWSDBServiceCredentialsProvider(credential_name)
    elif cloud_provider.lower() == "azure":
        return getAzureDBServiceCredentialsProvider(credential_name)
    elif cloud_provider.lower() == "gcp":
        return getGCPDBServiceCredentialsProvider(credential_name)
    else:
        raise Exception("Unsupported cloud provider: " + cloud_provider)
