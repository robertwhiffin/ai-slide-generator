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

"""
A worker for streaming foreachBatch in Spark Connect.
Usually this is ran on the driver side of the Spark Connect Server.
"""
import os

from pyspark.util import local_connect_and_auth
from pyspark.serializers import (
    write_int,
    read_long,
    UTF8Deserializer,
    CPickleSerializer,
)
from pyspark import worker
from pyspark.sql.connect.session import SparkSession
from pyspark.util import handle_worker_exception
from typing import IO
from pyspark.worker_util import check_python_version, setup_broadcasts, setup_spark_files

from databricks.connect.uds_channel_builder import UDSChannelBuilder  # EDGE

pickle_ser = CPickleSerializer()
utf8_deserializer = UTF8Deserializer()


spark = None


def main(infile: IO, outfile: IO) -> None:
    global spark

    log_name = "Streaming ForeachBatch worker"

    def process(df_id, batch_id):  # type: ignore[no-untyped-def]
        global spark
        if should_use_cloned_session:
            feb_session = spark_connect_cloned_session
        else:
            feb_session = spark_connect_session
        # We use the cloned streaming session to execute the user function.
        session_id = feb_session.session_id # EDGE
        print(f"{log_name} Started batch {batch_id} with DF id {df_id} and session id {session_id}")
        batch_df = feb_session._create_remote_dataframe(df_id) # EDGE
        func(batch_df, batch_id)
        print(
            f"{log_name} Completed batch {batch_id} with DF id {df_id} and session id {session_id}"
        )

    # BEGIN-EDGE
    def get_spark_session(
        connect_url, session_id, credentials_key, is_cloned_session = False
    ):  # type: ignore[no-untyped-def]
        # To attach to the existing SparkSession, we're setting the session_id in the URL.
        spark_connect_url = connect_url + ";session_id=" + session_id
        if spark_connect_url.lower().startswith("unix"):  # Used in process-isolation mode.
            builder = UDSChannelBuilder(spark_connect_url)
            builder.set("x-databricks-local-credentials-key", credentials_key)
            builder.set("session_id", session_id)
            session_builder = SparkSession.builder.channelBuilder(builder)
        else:
            session_builder = SparkSession.builder.remote(spark_connect_url)

        if is_cloned_session:
            # Use create() here because we need to create a new client session for cloned session.
            session = session_builder.create()
        else:
            session = session_builder.getOrCreate()
        assert session.session_id == session_id
        return session
    # END-EDGE

    try:
        check_python_version(infile)

        # Enable Spark Connect Mode
        os.environ["SPARK_CONNECT_MODE_ENABLED"] = "1"

        connect_url = os.environ["SPARK_CONNECT_LOCAL_URL"]
        root_session_id = utf8_deserializer.loads(infile)  # EDGE
        credentials_key = utf8_deserializer.loads(infile)  # EDGE
        should_use_cloned_session_str = utf8_deserializer.loads(infile)  # EDGE
        should_use_cloned_session = should_use_cloned_session_str.lower() == "true" # EDGE
        cloned_session_id = utf8_deserializer.loads(infile)  # EDGE

        print(f"{log_name} is starting with " f"url {connect_url} and "
              f"root sessionId {root_session_id}.")

        # BEGIN-EDGE
        # We need to set up the root session first because reading the user func requires a Spark
        # session to be set up. But at this stage, the cloned session is not available yet. What we
        # do here is:
        # 1. Set up the root session and initialize the Python worker.
        # 2. Set up the cloned session and use it to execute the user function.
        spark_connect_session = get_spark_session(
            connect_url, root_session_id, credentials_key
        )
        print(f"finished setting up the root session {root_session_id}.")
        # END-EDGE
        spark = spark_connect_session

        setup_spark_files(infile)
        setup_broadcasts(infile)

        func = worker.read_command(pickle_ser, infile)
        write_int(0, outfile)
        outfile.flush()

        cloned_session_set = False # EDGE
        while True:
            df_ref_id = utf8_deserializer.loads(infile)
            batch_id = read_long(infile)
            # BEGIN-EDGE
            # We only need to set up the cloned session once when cloned session is enabled.
            if not cloned_session_set and should_use_cloned_session:
                print(f"setting up the cloned session {cloned_session_id}.")
                spark_connect_cloned_session = get_spark_session(
                    connect_url, cloned_session_id, credentials_key, True
                )
                spark = spark_connect_cloned_session
                print(f"finished setting up the cloned session {cloned_session_id}.")
                cloned_session_set = True
            # END-EDGE

            # Handle errors inside Python worker. Write 0 to outfile if no errors and write -2 with
            # traceback string if error occurs.
            process(df_ref_id, int(batch_id))
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
    # There could be a long time between each micro batch.
    sock.settimeout(None)
    write_int(os.getpid(), sock_file)
    sock_file.flush()
    main(sock_file, sock_file)
