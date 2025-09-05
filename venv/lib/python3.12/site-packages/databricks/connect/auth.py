#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2020-present Databricks, Inc.
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

from typing import Any, List, Optional, Tuple

import grpc
import urllib.parse

from databricks.connect.headers import Headers
from databricks.sdk.core import Config
from pyspark.sql.connect.client import ChannelBuilder
from pyspark.sql.connect.logging import logger


def maybe_append_port(url) -> str:
    return f"{url.netloc}:443" if url.port is None else url.netloc


class DatabricksChannelBuilder(ChannelBuilder):
    def __init__(
        self,
        config: Config,
        user_agent: str = "",
        channelOptions: Optional[List[Tuple[str, Any]]] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        params = {ChannelBuilder.PARAM_USER_AGENT: user_agent}
        if headers is not None:
            params.update(headers)

        if Headers.SESSION_ID in params:
            # use the session id provided in the header as the spark session id
            params[ChannelBuilder.PARAM_SESSION_ID] = params[Headers.SESSION_ID]

        super().__init__(channelOptions=channelOptions, params=params)

        self._config: Config = config
        self.url = urllib.parse.urlparse(config.host)

    def toChannel(self) -> grpc.Channel:
        """This method creates secure channel with :class:DatabricksAuthMetadataPlugin
        enabled, which handles refresh of HTTP headers for OAuth, like U2M flow and
        Service Principal flows."""
        from grpc import _plugin_wrapping  # pylint: disable=cyclic-import
        ssl_creds = grpc.ssl_channel_credentials()
        databricks_creds = _plugin_wrapping.metadata_plugin_call_credentials(
            UnifiedAuthMetadata(self._config), None)
        composite_creds = grpc.composite_channel_credentials(ssl_creds, databricks_creds)

        destination = maybe_append_port(self.url)
        logger.debug("Creating secure channel to %s", destination)
        return self._secure_channel(destination, composite_creds)

    @property
    def host(self) -> str:
        return self._config.hostname


class UnifiedAuthMetadata(grpc.AuthMetadataPlugin):
    def __init__(self, config: Config):
        self._config = config

    def __call__(
        self,
        context: grpc.AuthMetadataContext,
        callback: grpc.AuthMetadataPluginCallback,
    ) -> None:
        try:
            headers = self._config.authenticate()
            metadata = ()
            # these are HTTP headers returned by Databricks SDK
            for k, v in headers.items():
                # gRPC requires headers to be lower-cased
                metadata += ((k.lower(), v), )
            callback(metadata, None)
        except Exception as e:
            # We have to include the 'failed to connect to all addresses' string, because that
            # is the current way to propagate a terminal error when the client cannot connect
            # to any endpoint and thus cannot be retried.
            #
            # See pyspark.sql.connect.client.SparkConnectClient.retry_exception
            msg = f"failed to connect to all addresses using {self._config.auth_type} auth: {e}"

            # Add debug information from SDK Config to the end of the error message.
            msg = self._config.wrap_debug_info(msg)
            callback((), ValueError(msg))
