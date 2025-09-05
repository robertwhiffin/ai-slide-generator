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

# APIs defined in this module are designed for Ray-on-Spark framework.

import os
from collections import namedtuple
from typing import Optional

import pyarrow as pa

from pyspark.util import _create_local_socket
from pyspark.sql import DataFrame
from pyspark.sql import SparkSession
from pyspark.serializers import read_with_length, write_with_length
from pyspark.sql.pandas.utils import require_minimum_pyarrow_version
from pyspark.errors import PySparkRuntimeError


ChunkMeta = namedtuple("ChunkMeta", ["id", "row_count", "byte_count"])

require_minimum_pyarrow_version()


def persistDataFrameAsChunks(
    dataframe: DataFrame, max_bytes_per_chunk: Optional[int]
) -> list[ChunkMeta]:
    """Persist and materialize the spark dataframe as chunks, each chunk is an arrow batch.
    It tries to persist data to spark worker memory firstly, if memory is not sufficient,
    then it fallbacks to persist spilled data to spark worker local disk.
    Return the list of tuple (chunk_id, chunk_row_count, chunk_byte_count).
    This function is only available when it is called from spark driver process.

    .. versionadded:: 4.0.0

    Parameters
    ----------
    dataframe : DataFrame
        the spark DataFrame to be persisted as chunks
    max_bytes_per_chunk : int
        an integer representing max bytes per chunk,
        if None, use default chunk size of 32MB.

    Notes
    -----
    This API is a developer API.
    """
    if max_bytes_per_chunk is None:
        max_bytes_per_chunk = 32 * 1024 * 1024

    spark = dataframe.sparkSession
    if spark is None:
        raise PySparkRuntimeError("Active spark session is required.")

    sc = spark.sparkContext
    if not sc._jvm.org.apache.spark.api.python.CachedArrowBatchServer.isEnabled():
        raise PySparkRuntimeError(
            "In order to use 'persistDataFrameAsChunks' API, you must set spark "
            "cluster config 'spark.databricks.pyspark.dataFrameChunk.enabled' to 'true', "
            "and you must disable 'spark.databricks.acl.dfAclsEnabled' configuration."
        )

    python_api = sc._jvm.org.apache.spark.sql.api.python  # type: ignore[union-attr]

    chunk_meta_list = list(
        python_api.ChunkReadUtils.persistDataFrameAsArrowBatchChunks(
            dataframe._jdf, max_bytes_per_chunk
        )
    )
    return [
        ChunkMeta(java_chunk_meta.id(), java_chunk_meta.rowCount(), java_chunk_meta.byteCount())
        for java_chunk_meta in chunk_meta_list
    ]


def unpersistChunks(chunk_ids: list[str]) -> None:
    """Unpersist chunks by chunk ids.
    This function is only available when it is called from spark driver process.

    .. versionadded:: 4.0.0

    Parameters
    ----------
    chunk_ids : list[str]
        A list of chunk ids

    Notes
    -----
    This API is a developer API.
    """
    sc = SparkSession.getActiveSession().sparkContext  # type: ignore[union-attr]
    python_api = sc._jvm.org.apache.spark.sql.api.python  # type: ignore[union-attr]
    python_api.ChunkReadUtils.unpersistChunks(chunk_ids)


def readChunk(chunk_id: str) -> pa.Table:
    """Read chunk by id, return this chunk as an arrow table.
    You can call this function from spark driver, spark python UDF python,
    descendant process of spark driver, or descendant process of spark python UDF worker.

    .. versionadded:: 4.0.0

    Parameters
    ----------
    chunk_id : str
        a string of chunk id

    Notes
    -----
    This API is a developer API.
    """

    if "PYSPARK_EXECUTOR_CACHED_ARROW_BATCH_SERVER_PORT" not in os.environ:
        raise PySparkRuntimeError(
            "In order to use dataframe chunk read API, you must set spark "
            "cluster config 'spark.databricks.pyspark.dataFrameChunk.enabled' to 'true',"
            "and you must call 'readChunk' API in pyspark driver, pyspark UDF,"
            "descendant process of pyspark driver, or descendant process of pyspark "
            "UDF worker."
        )

    port = int(os.environ["PYSPARK_EXECUTOR_CACHED_ARROW_BATCH_SERVER_PORT"])
    auth_secret = os.environ["PYSPARK_EXECUTOR_CACHED_ARROW_BATCH_SERVER_SECRET"]

    sockfile = _create_local_socket((port, auth_secret))
    pa_reader = None
    try:
        write_with_length("read_chunk".encode("utf-8"), sockfile)
        write_with_length(chunk_id.encode("utf-8"), sockfile)
        sockfile.flush()
        err_message = read_with_length(sockfile).decode("utf-8")

        if err_message != "ok":
            raise PySparkRuntimeError(f"Read chunk '{chunk_id}' failed (error: {err_message}).")

        pa_reader = pa.ipc.open_stream(sockfile)
        batch_list = []
        for batch in pa_reader:
            batch_list.append(batch)

        assert len(batch_list) == 1
        arrow_batch = batch_list[0]

        arrow_table = pa.Table.from_batches([arrow_batch])

        return arrow_table
    finally:
        if pa_reader is not None:
            if hasattr(pa_reader, "close"):
                pa_reader.close()
        sockfile.close()
