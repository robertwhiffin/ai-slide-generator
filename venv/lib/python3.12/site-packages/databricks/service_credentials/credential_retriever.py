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

import sys
import os
import grpc
from databricks.service_credentials.proto import (
    temporary_credential_pb2,
    temporary_credential_pb2_grpc,
)
from dataclasses import dataclass


class SingletonMeta(type):
    """Metaclass for enforcing the Singleton pattern."""

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

    @classmethod
    def reset_instance(cls):
        """Resets all singleton instances (for testing purposes)."""
        cls._instances = {}


@dataclass
class AwsTempCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    access_point: str
    expiration_time_epoch_ms: int


@dataclass
class AzureAadCredentials:
    aad_token: str
    expiration_time_epoch_ms: int


@dataclass
class GcpOauthToken:
    oauth_token: str
    expiration_time_epoch_ms: int


class CredentialRetriever(metaclass=SingletonMeta):
    """Singleton class for retrieving temporary credentials from a gRPC service living in the Spark Container."""

    AWS_CREDENTIALS = "aws_temp_credentials"
    AZURE_CREDENTIALS = "azure_aad"
    GCP_CREDENTIALS = "gcp_oauth_token"

    def __init__(self):
        self._socket_path = None
        self._channel = None
        self._stub = None
        self._sandbox_uuid = None

        socket_path = os.getenv("SERVICE_CREDENTIAL_SOCKET_PATH")
        if not socket_path:
            raise ValueError(
                "Environment variable SERVICE_CREDENTIAL_SOCKET_PATH is not set."
            )

        if not os.path.exists(socket_path):
            raise FileNotFoundError(f"Socket file at {socket_path} does not exist.")

        # Get the sandbox UUID for verification
        self._sandbox_uuid = os.getenv("SANDBOX_UUID")

        # Set socket path before creating channel
        self._socket_path = socket_path
        self._channel = grpc.insecure_channel(f"unix:{self._socket_path}")
        self._stub = (
            temporary_credential_pb2_grpc.TemporaryCredentialRetrieverServiceStub(
                self._channel
            )
        )

    def reset(self):
        """Resets the CredentialRetriever instance, allowing reinitialization."""
        try:
            # Close the channel
            self._channel.close()
        except Exception as e:
            # Channel might already be closed
            print(
                "Tried to close channel as part of reset, but failed with error.",
                e,
                file=sys.stderr,
            )
            pass
        SingletonMeta.reset_instance()

    def _get_credentials(
        self, credential_name=None, expected_credential_type=None, **kwargs
    ):
        """Retrieve credentials from gRPC service, based on the credential name + scope/resources. If credential_name is None, the default credential is returned."""
        if not hasattr(self, "_stub") or self._stub is None:
            raise RuntimeError(
                "Socket path is not set or gRPC stub is not initialized."
            )

        # Create the request with the sandbox UUID for verification
        request = temporary_credential_pb2.TemporaryCredentialRequest(
            credential_name=credential_name, sandbox_uuid=self._sandbox_uuid, **kwargs
        )

        try:
            response = self._stub.GetCredential(request)
        except grpc.RpcError as e:
            raise RuntimeError(f"Error retrieving credentials: {e}") from e

        if not hasattr(response, "credentials") or not hasattr(
            response.credentials, "expiration_time"
        ):
            raise ValueError(
                "Response does not contain valid credentials or expiration time."
            )

        return self._parse_credentials(
            response.credentials,
            response.credentials.expiration_time,
            expected_credential_type,
        )

    def _parse_credentials(
        self, credential, expiration_time_epoch_ms, expected_credential_type
    ):
        """Determine the credential type and return the appropriate credential object."""

        credential_classes = {
            self.AWS_CREDENTIALS: lambda creds: AwsTempCredentials(
                access_key_id=creds.aws_temp_credentials.access_key_id,
                secret_access_key=creds.aws_temp_credentials.secret_access_key,
                session_token=creds.aws_temp_credentials.session_token,
                access_point=creds.aws_temp_credentials.access_point,
                expiration_time_epoch_ms=expiration_time_epoch_ms,
            ),
            self.AZURE_CREDENTIALS: lambda creds: AzureAadCredentials(
                aad_token=creds.azure_aad.aad_token,
                expiration_time_epoch_ms=expiration_time_epoch_ms,
            ),
            self.GCP_CREDENTIALS: lambda creds: GcpOauthToken(
                oauth_token=creds.gcp_oauth_token.oauth_token,
                expiration_time_epoch_ms=expiration_time_epoch_ms,
            ),
        }

        cred_type = credential.WhichOneof("credentials")
        if (
            expected_credential_type is not None
            and cred_type != expected_credential_type
        ):
            raise ValueError(
                f"Expected credential type {expected_credential_type} but received {cred_type}"
            )

        if cred_type in credential_classes:
            return credential_classes[cred_type](credential)

        raise ValueError(f"Received unexpected credential type: {cred_type}")

    def get_aws_credential(self, credential_name):
        """Retrieve AWS temporary credentials."""
        return self._get_credentials(
            credential_name, expected_credential_type=self.AWS_CREDENTIALS
        )

    def get_azure_credential(self, credential_name, resources):
        """Retrieve Azure Active Directory credentials."""
        return self._get_credentials(
            credential_name,
            expected_credential_type=self.AZURE_CREDENTIALS,
            resources=temporary_credential_pb2.AzureResources(values=resources),
        )

    def get_gcp_credential(self, credential_name, scopes):
        """Retrieve GCP OAuth credentials."""
        return self._get_credentials(
            credential_name,
            expected_credential_type=self.GCP_CREDENTIALS,
            scopes=temporary_credential_pb2.GCPScopes(values=scopes),
        )
