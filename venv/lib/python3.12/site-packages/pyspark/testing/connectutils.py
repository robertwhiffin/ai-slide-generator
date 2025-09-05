#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import shutil
import tempfile
import typing
import os
import functools
import unittest
import uuid
import contextlib

grpc_requirement_message = None
try:
    import grpc
except ImportError as e:
    grpc_requirement_message = str(e)
have_grpc = grpc_requirement_message is None


grpc_status_requirement_message = None
try:
    import grpc_status
except ImportError as e:
    grpc_status_requirement_message = str(e)
have_grpc_status = grpc_status_requirement_message is None

googleapis_common_protos_requirement_message = None
try:
    from google.rpc import error_details_pb2
except ImportError as e:
    googleapis_common_protos_requirement_message = str(e)
have_googleapis_common_protos = googleapis_common_protos_requirement_message is None

graphviz_requirement_message = None
try:
    import graphviz
except ImportError as e:
    graphviz_requirement_message = str(e)
have_graphviz: bool = graphviz_requirement_message is None

from pyspark import Row, SparkConf
from pyspark.util import is_remote_only
from pyspark.testing.utils import PySparkErrorTestUtils
from pyspark.testing.sqlutils import (
    have_pandas,
    pandas_requirement_message,
    pyarrow_requirement_message,
    SQLTestUtils,
)
from pyspark.sql.session import SparkSession as PySparkSession


connect_requirement_message = (
    pandas_requirement_message
    or pyarrow_requirement_message
    or grpc_requirement_message
    or googleapis_common_protos_requirement_message
    or grpc_status_requirement_message
)
should_test_connect: str = typing.cast(str, connect_requirement_message is None)

if should_test_connect:
    from pyspark.sql.connect.dataframe import DataFrame
    from pyspark.sql.connect.plan import Read, Range, SQL, LogicalPlan
    from pyspark.sql.connect.session import SparkSession


disable_test_for_uc: bool = os.getenv("ENABLE_UNITY_CATALOG_TESTS", "false").lower() == "true"


class TrailerInspectInterceptor(grpc.UnaryStreamClientInterceptor):
    def __init__(self):
        self._trailers = []

    def intercept_unary_stream(self, continuation, client_call_details, request):
        # Intercept the call and get the response iterator
        response_iterator = continuation(client_call_details, request)

        # Wrap the response iterator to inspect the trailers after iteration
        return self._wrap_response_iterator(response_iterator, client_call_details.method)

    def _wrap_response_iterator(self, response_iterator, method):
        for response in response_iterator:
            yield response
        # After iteration is complete, inspect trailers
        trailers = response_iterator.trailing_metadata()
        self._trailers += trailers

    def trailers(self):
        return self._trailers

    def reset_trailers(self):
        self._trailers.clear()


class MockRemoteSession:
    def __init__(self):
        self.hooks = {}
        self.session_id = str(uuid.uuid4())
        self.is_mock_session = True

    def set_hook(self, name, hook):
        self.hooks[name] = hook

    def drop_hook(self, name):
        self.hooks.pop(name)

    def __getattr__(self, item):
        if item not in self.hooks:
            raise LookupError(f"{item} is not defined as a method hook in MockRemoteSession")
        return functools.partial(self.hooks[item])


@unittest.skipIf(not should_test_connect, connect_requirement_message)
class PlanOnlyTestFixture(unittest.TestCase, PySparkErrorTestUtils):
    if should_test_connect:

        class MockDF(DataFrame):
            """Helper class that must only be used for the mock plan tests."""

            def __init__(self, plan: LogicalPlan, session: SparkSession):
                super().__init__(plan, session)

            def __getattr__(self, name):
                """All attributes are resolved to columns, because none really exist in the
                mocked DataFrame."""
                return self[name]

        @classmethod
        def _read_table(cls, table_name):
            return cls._df_mock(Read(table_name))

        @classmethod
        def _udf_mock(cls, *args, **kwargs):
            return "internal_name"

        @classmethod
        def _df_mock(cls, plan: LogicalPlan) -> MockDF:
            return PlanOnlyTestFixture.MockDF(plan, cls.connect)

        @classmethod
        def _session_range(
            cls,
            start,
            end,
            step=1,
            num_partitions=None,
        ):
            return cls._df_mock(Range(start, end, step, num_partitions))

        @classmethod
        def _session_sql(cls, query):
            return cls._df_mock(SQL(query))

        if have_pandas:

            @classmethod
            def _with_plan(cls, plan):
                return cls._df_mock(plan)

        @classmethod
        def setUpClass(cls):
            cls.connect = MockRemoteSession()
            cls.session = SparkSession.builder.remote().getOrCreate()
            cls.tbl_name = "test_connect_plan_only_table_1"

            cls.connect.set_hook("readTable", cls._read_table)
            cls.connect.set_hook("range", cls._session_range)
            cls.connect.set_hook("sql", cls._session_sql)
            cls.connect.set_hook("with_plan", cls._with_plan)

        @classmethod
        def tearDownClass(cls):
            cls.connect.drop_hook("readTable")
            cls.connect.drop_hook("range")
            cls.connect.drop_hook("sql")
            cls.connect.drop_hook("with_plan")


@unittest.skipIf(not should_test_connect, connect_requirement_message)
class ReusedConnectTestCase(unittest.TestCase, SQLTestUtils, PySparkErrorTestUtils):
    """
    Spark Connect version of :class:`pyspark.testing.sqlutils.ReusedSQLTestCase`.
    """

    @classmethod
    def conf(cls):
        """
        Override this in subclasses to supply a more specific conf
        """
        conf = SparkConf(loadDefaults=False)
        # Make the server terminate reattachable streams every 1 second and 123 bytes,
        # to make the tests exercise reattach.
        if conf._jconf is not None:
            conf._jconf.remove("spark.master")
        conf.set("spark.connect.execute.reattachable.senderMaxStreamDuration", "1s")
        conf.set("spark.connect.execute.reattachable.senderMaxStreamSize", "123")
        conf.set("spark.connect.session.connectML.enabled", "true")  # EDGE
        # Set a static token for all tests so the parallelism doesn't overwrite each
        # tests' environment variables
        conf.set("spark.connect.authenticate.token", "deadbeef")
        return conf

    @classmethod
    def master(cls):
        return os.environ.get("SPARK_CONNECT_TESTING_REMOTE", "local[4]")

    @classmethod
    def setUpClass(cls):
        cls.spark = (
            PySparkSession.builder.config(conf=cls.conf())
            .appName(cls.__name__)
            .remote(cls.master())
            # BEGIN-EDGE
            # Configure the cloud fetch mocking.
            .config(
                "spark.databricks.cloudfetch.requesterClassName",
                "org.apache.spark.sql.test.MockCloudPresignedUrlRequester",
            )
            .config("spark.thriftserver.testing.storageServer.port", "15050")
            # Disabled as this feature is DBSQL-only, and many of the empty columns tests fail.
            .config("spark.databricks.photon.arrowCollect.nativeArrowConversionEnabled", "false")
            # END-EDGE
            .getOrCreate()
        )

        # BEGIN-EDGE
        # Start the storage server:
        assert PySparkSession._instantiatedSession is not None
        cls._gateway = PySparkSession._instantiatedSession.sparkContext._gateway
        cls._gateway.jvm.org.apache.spark.sql.test.MockCloudStorageServer.startServer()
        # END-EDGE

        cls.update_client_for_uc(cls.spark)

        cls.interceptor = TrailerInspectInterceptor()
        cls.spark._client._builder.add_interceptor(cls.interceptor)
        cls.spark._client.rebuild_connection_for_testing()

        cls._legacy_sc = None
        if not is_remote_only():
            cls._legacy_sc = PySparkSession._instantiatedSession._sc
        cls.tempdir = tempfile.NamedTemporaryFile(delete=False)
        os.unlink(cls.tempdir.name)
        cls.testData = [Row(key=i, value=str(i)) for i in range(100)]
        cls.df = cls.spark.createDataFrame(cls.testData)

    # BEGIN-EDGE
    @classmethod
    def update_client_for_uc(cls, spark):
        """Helper method that sets up necessary metadata for UC testing.

        When UC is configured properly for the tests, the server expects a credentials
        scope to be present. The token scope is created from the tokens extracted
        from the headers and the API URL.

        The metadat can always be present for testing.
        """
        if os.getenv("ENABLE_PY4J_SECURITY", "0") == "1":
            spark._client._builder.set("x-databricks-non-uc-user-token", "super")
            spark._client._artifact_manager._metadata.append(
                ("x-databricks-non-uc-user-token", "super")
            )

        spark._client._builder.set("x-databricks-api-url", "http://other.host")
        spark._client._artifact_manager._metadata.append(
            ("x-databricks-api-url", "http://other.host")
        )
        spark._client._builder.set("x-databricks-user-token", "super")
        spark._client._artifact_manager._metadata.append(("x-databricks-user-token", "super"))

    # END-EDGE

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tempdir.name, ignore_errors=True)
        # BEGIN-EDGE
        if cls._gateway is not None:
            cls._gateway.jvm.org.apache.spark.sql.test.MockCloudStorageServer.stopServer()
        # END-EDGE
        cls.spark.stop()

    def setUp(self) -> None:
        # force to clean up the ML cache before each test
        self.spark.client._cleanup_ml_cache()

    def test_assert_remote_mode(self):
        from pyspark.sql import is_remote

        self.assertTrue(is_remote())

    def quiet(self):
        from pyspark.testing.utils import QuietTest

        if self._legacy_sc is not None:
            return QuietTest(self._legacy_sc)
        else:
            return contextlib.nullcontext()


@unittest.skipIf(
    not should_test_connect or is_remote_only(),
    connect_requirement_message or "Requires JVM access",
)
class ReusedMixedTestCase(ReusedConnectTestCase, SQLTestUtils):
    @classmethod
    def setUpClass(cls):
        super(ReusedMixedTestCase, cls).setUpClass()
        # Disable the shared namespace so pyspark.sql.functions, etc point the regular
        # PySpark libraries.
        os.environ["PYSPARK_NO_NAMESPACE_SHARE"] = "1"

        cls.connect = cls.spark  # Switch Spark Connect session and regular PySpark session.
        cls.spark = PySparkSession._instantiatedSession
        assert cls.spark is not None

    @classmethod
    def tearDownClass(cls):
        try:
            # Stopping Spark Connect closes the session in JVM at the server.
            cls.spark = cls.connect
            del os.environ["PYSPARK_NO_NAMESPACE_SHARE"]
        finally:
            super(ReusedMixedTestCase, cls).tearDownClass()

    def setUp(self) -> None:
        # force to clean up the ML cache before each test
        self.connect.client._cleanup_ml_cache()

    def compare_by_show(self, df1, df2, n: int = 20, truncate: int = 20):
        from pyspark.sql.classic.dataframe import DataFrame as SDF
        from pyspark.sql.connect.dataframe import DataFrame as CDF

        assert isinstance(df1, (SDF, CDF))
        if isinstance(df1, SDF):
            str1 = df1._jdf.showString(n, truncate, False)
        else:
            str1 = df1._show_string(n, truncate, False)

        assert isinstance(df2, (SDF, CDF))
        if isinstance(df2, SDF):
            str2 = df2._jdf.showString(n, truncate, False)
        else:
            str2 = df2._show_string(n, truncate, False)

        self.assertEqual(str1, str2)

    def test_assert_remote_mode(self):
        # no need to test this in mixed mode
        pass
