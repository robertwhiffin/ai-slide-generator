#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2019 Databricks, Inc.
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
from pyspark.sql import SparkSession
from pyspark.sql.connect.session import SparkSession as RemoteSession, SparkConnectClient
from typing import cast, Optional


class DBUtils:
    """
    This class exists to satisfy API backwards compatibility with applications using DB Connect v1.

    .. deprecated:: 13.0
        Switch to DBUtils in the Databricks Python SDK.
    """

    def __init__(self, spark: Optional[SparkSession] = None):
        if spark is None:
            spark = SparkSession.builder.getOrCreate()

        nb_dbutils = self._try_get_notebook_dbutils()
        if nb_dbutils is not None:
            # Running in a Databricks notebook
            self._utils = nb_dbutils

            # When running in a notebook add all the DBUtils handlers
            # from the global object.
            self.entry_point = self._utils.entry_point
            self.credentials = self._utils.credentials
            self.library = self._utils.library
            self.notebook = self._utils.notebook
            self.preview = self._utils.preview
            self.widgets = self._utils.widgets
            self.jobs = self._utils.jobs
        else:
            # Running locally
            from databricks.sdk.dbutils import RemoteDbUtils

            if not isinstance(spark, RemoteSession):
                raise TypeError(
                    "DBUtils can be initialized only with a remote spark session."
                    + "See Databricks Connect on how to setup a remote spark session."
                )

            client: SparkConnectClient = cast(RemoteSession, spark).client
            config = self._get_config(client)
            self._utils = RemoteDbUtils(config)

        self.fs = self._utils.fs
        self.secrets = self._utils.secrets

    def get_dbutils(self, spark: SparkSession):
        # API exists for backwards compatibility
        if hasattr(spark, "_sc"):
            # Running in a Databricks notebook
            import IPython

            return IPython.get_ipython().user_ns["dbutils"]
        else:
            return self

    @staticmethod
    def _try_get_notebook_dbutils():
        # check if we are running in a Databricks notebook
        try:
            import IPython  # noqa

            user_ns = getattr(IPython.get_ipython(), "user_ns", {})
            if "dbutils" in user_ns:
                return user_ns["dbutils"]
            return None
        except ImportError:
            # IPython must be present in a Databricks notebook. Without this
            # module we cannot access the context objects.
            return None

    @staticmethod
    def _get_config(client: SparkConnectClient):
        from databricks.sdk.core import Config

        channel_builder = client._builder

        if hasattr(channel_builder, "_config"):
            # Reuse SDK Client that is initialized in the DatabricksChannelBuilder,
            # so that we don't have more than one OAuth token caches. We do use
            # hasattr() instead of importing databricks.connect.auth.DatabricksChannelBuilder
            # because //python:pyspark.tests.test_dbutils cannot import from
            # databricks.connect.*
            config = channel_builder._config
            assert isinstance(config, Config)
            return config

        # Create sdk.Config from OSS connection string format
        url = channel_builder.url
        splits = url.params.split(";")
        params = {}
        for split in splits:
            inner_split = split.split("=")
            if len(inner_split) != 2:
                raise RuntimeError(f"Invalid connection string: {url}")

            params[inner_split[0]] = inner_split[1]

        if client.host is None or client.token is None or "x-databricks-cluster-id" not in params:
            raise RuntimeError(f"Invalid connection string: {url}")

        return Config(
            host=client.host,
            token=client.token,
            cluster_id=params["x-databricks-cluster-id"],
        )
