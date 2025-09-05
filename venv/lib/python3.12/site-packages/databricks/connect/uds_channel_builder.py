#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2021-present Databricks, Inc.
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

import grpc
import urllib.parse
from typing import Dict, Optional

from pyspark.sql.connect.client import ChannelBuilder
from pyspark.errors import PySparkValueError

UDS_SCHEME = "unix"


class UDSChannelBuilder(ChannelBuilder):
    def __init__(self, connectionString: str):
        super().__init__()

        if connectionString[:7] != (UDS_SCHEME + "://"):
            raise PySparkValueError(
                errorClass="INVALID_CONNECT_URL",
                messageParameters={
                    "detail": f"URL scheme must be set to `{UDS_SCHEME}`. Please update "
                              f"the URL to follow the correct format.",
                },
            )

        # Urllib recognize the path and parameters for URL differently
        # if the scheme is "unix". We are replacing the scheme with "http"
        # here to be able to parse parameters correctly. For example:
        # urllib.parse.urlparse("unix://ab.com/;a=b;c=d")
        # ParseResult(scheme='unix', netloc='ab.com', path='/;a=b;c=d', params='', ...)
        # urllib.parse.urlparse("http://ab.com/;a=b;c=d")
        # ParseResult(scheme='http', netloc='ab.com', path='/', params='a=b;c=d', ...)
        tmp_url = "http" + connectionString[len(UDS_SCHEME) :]
        self.url = urllib.parse.urlparse(tmp_url)
        self.path = connectionString.split(";")[0]

        self._extract_attributes()

    def _extract_attributes(self) -> None:
        if len(self.url.params) > 0:
            try:
                params = urllib.parse.parse_qsl(self.url.params, strict_parsing=True, separator=";")
            except ValueError:
                raise PySparkValueError(
                    errorClass="INVALID_CONNECT_URL",
                    messageParameters={
                        "detail": "Parameters should be provided as "
                        "key-value pairs separated by an equal sign (=). Please update "
                        "the parameter to follow the correct format, e.g., 'key=value'.",
                    },
                )
            for key, value in params:
                self.set(key, urllib.parse.unquote(value))

    def toChannel(self) -> grpc.Channel:
        return self._insecure_channel(self.path)

    @property
    def host(self) -> str:
        return self.path
