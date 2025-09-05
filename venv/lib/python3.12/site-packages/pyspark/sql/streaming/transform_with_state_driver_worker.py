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

import os
import json
from typing import Any, Iterator, TYPE_CHECKING

from pyspark.util import local_connect_and_auth
from pyspark.serializers import (
    write_int,
    read_bool,
    read_int,
    UTF8Deserializer,
    CPickleSerializer,
)
from pyspark import worker
from pyspark.util import handle_worker_exception
from typing import IO
from pyspark.worker_util import check_python_version, setup_broadcasts, setup_spark_files
from pyspark.sql.streaming.stateful_processor_api_client import StatefulProcessorApiClient
from pyspark.sql.streaming.stateful_processor_util import TransformWithStateInPandasFuncMode
from pyspark.sql.types import StructType

# BEGIN-EDGE
from pyspark._engine_adapters import IS_ENGINE_PYSPARK
if IS_ENGINE_PYSPARK:
    from pyspark.util import PythonEvalType
    from pyspark._engine_adapters import convert_return_type, engine_pyspark_function_converter
# END-EDGE

if TYPE_CHECKING:
    from pyspark.sql.pandas._typing import (
        DataFrameLike as PandasDataFrameLike,
    )

pickle_ser = CPickleSerializer()
utf8_deserializer = UTF8Deserializer()


def main(infile: IO, outfile: IO) -> None:
    check_python_version(infile)

    log_name = "Streaming TransformWithStateInPandas driver Python worker"
    print(f"Starting {log_name}.\n")

    def process(
        processor: StatefulProcessorApiClient,
        mode: TransformWithStateInPandasFuncMode,
        key: Any,
        input: Iterator["PandasDataFrameLike"],
    ) -> None:
        print(f"{log_name} Starting execution of UDF: {func}.\n")
        func(processor, mode, key, input)
        print(f"{log_name} Completed execution of UDF: {func}.\n")

    try:
        # BEGIN-EDGE
        # This is only used in DBR because Scala sender sends additional spark files
        # and broadcast vars.
        setup_spark_files(infile)
        setup_broadcasts(infile)
        # END-EDGE

        func, return_type = worker.read_command(pickle_ser, infile)
        # BEGIN-EDGE
        # ES-1538976: transformWithState needs to convert TransformWithStateInPandasUdfUtils between
        #   client and engine namespaces in serverless under engine pyspark.
        if IS_ENGINE_PYSPARK:
            func = engine_pyspark_function_converter(PythonEvalType.SQL_TRANSFORM_WITH_STATE_PANDAS_UDF, func)
            return_type = convert_return_type(return_type)
        # END-EDGE
        print(
            f"{log_name} finish init stage of Python runner. Received UDF from JVM: {func}, "
            f"received return type of UDF: {return_type}.\n"
        )
        # send signal for getting args
        write_int(0, outfile)
        outfile.flush()

        # This driver runner will only be used on the first batch of a query,
        # and the following code block should be only run once for each query run
        is_isolated_tws_enabled = read_bool(infile)
        state_server_id = read_int(infile)
        key_schema = StructType.fromJson(json.loads(utf8_deserializer.loads(infile)))
        print(
            f"{log_name} received parameters for UDF. State server id: {state_server_id}, "
            f"key schema: {key_schema}.\n"
        )

        stateful_processor_api_client = StatefulProcessorApiClient(
            state_server_id, key_schema, is_driver=True, is_isolated_tws_enabled=is_isolated_tws_enabled)
        process(
            stateful_processor_api_client,
            TransformWithStateInPandasFuncMode.PRE_INIT,
            None,
            iter([]),
        )
        write_int(0, outfile)
        outfile.flush()
    except Exception as e:
        handle_worker_exception(e, outfile)
        outfile.flush()


if __name__ == "__main__":
    # Read information about how to connect back to the JVM from the environment.
    java_port = int(os.environ["PYTHON_WORKER_FACTORY_PORT"])
    auth_secret = os.environ["PYTHON_WORKER_FACTORY_SECRET"]
    (sock_file, sock) = local_connect_and_auth(java_port, auth_secret)
    write_int(os.getpid(), sock_file)
    sock_file.flush()
    main(sock_file, sock_file)
