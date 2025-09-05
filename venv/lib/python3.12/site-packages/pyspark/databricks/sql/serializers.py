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

"""
Serializers for PyArrow and pandas conversions for Databricks edge features.
See `pyspark.serializers` for more details.
"""
import math
import itertools

from pyspark.sql.pandas.serializers import (
    ArrowStreamGroupUDFSerializer,
    ArrowStreamPandasUDFSerializer,
    ArrowStreamSerializer,
    CogroupPandasUDFSerializer,
    read_int,
    write_int,
    SpecialLengths,
)
from pyspark.sql.pandas.utils import estimate_pandas_convert_as_arrow_size


def slice_pandas_frame(series, pandas_max_bytes_per_slice):
    for frame, t in series:
        # The logic here mimics the conversion from pandas to Spark DataFrame.
        estimated_data_size = estimate_pandas_convert_as_arrow_size(frame)
        num_slices = math.ceil(estimated_data_size / pandas_max_bytes_per_slice)
        length = len(frame)
        num_slices = min(num_slices, length)
        yield (
            (frame.iloc[i * length // num_slices : (i + 1) * length // num_slices], t)
            for i in range(0, num_slices)
        )


class GroupUDFSerializer(ArrowStreamPandasUDFSerializer):
    def __init__(
        self,
        timezone,
        safecheck,
        assign_cols_by_name,
        df_for_struct=False,
        max_prefetch=0,
        timely_flush_enabled=True,
        timely_flush_timeout_ms=100,
        max_bytes=-1,
    ):
        super(GroupUDFSerializer, self).__init__(
            timezone,
            safecheck,
            assign_cols_by_name,
            df_for_struct,
            max_prefetch,
            timely_flush_enabled,
            timely_flush_timeout_ms,
        )
        self.max_bytes = max_bytes

    def load_stream(self, stream):
        """
        Deserialize each grouped ArrowRecordBatches (in a complete streaming Arrow format) to
        pandas.Series. For example, the Arrow formats from JVM side as below are converted to
        each pandas DataFrame that contains each grouped data.

        +------+-----------------+------+------+-----------------+------+------+--------------------
        |Schema|            Batch| Batch|Schema|            Batch| Batch|Schema|           Batch ...
        +------+-----------------+------+------+-----------------+------+------+--------------------
        |    Arrow Streaming Format     |    Arrow Streaming Format     |    Arrow Streaming Form...

               +------------------------+      +------------------------+      +--------------------
               |pd.DF (by k1) v1, v2, v3|      |pd.DF (by k2) v1, v2, v3|      |                 ...
               +------------------------+      +------------------------+      +--------------------

        """
        import pyarrow as pa

        should_read_more = read_int(stream) == 1

        while should_read_more:
            batches = [batch for batch in ArrowStreamSerializer.load_stream(self, stream)]
            yield [
                self.arrow_to_pandas(c, i)
                for i, c in enumerate(pa.Table.from_batches(batches).itercolumns())
            ]
            should_read_more = read_int(stream) == 1

    def dump_stream(self, iterator, stream, timely_flush_enabled=True, timely_flush_timeout_ms=100):
        """
        Serialize each pandas DataFrame after applying the function into sized batches.
        It is different from OSS side because it slices each pandas DataFrame into smaller
        Arrow batches. For example, the pandas DataFrame outputs below are converted into
        one complete Arrow streaming format.

               +------------------------+------------------------+------------------------
               |pd.DF (by k1) v1, v2, v3|pd.DF (by k2) v1, v2, v3|                     ...
               +------------------------+------------------------+------------------------

        +------+--------+--------+------+--------+--------+------+--------+--------+------
        |Schema|   Batch|   Batch| Batch|   Batch|   Batch| Batch|   Batch|   Batch|   ...
        +------+--------+--------+------+--------+--------+------+--------+--------+------
        |                                 Arrow Streaming Format                       ...

        """
        assert self.max_bytes > 0

        def init_stream_yield_batches():
            should_write_start_length = True
            slices = (slice_pandas_frame(frames, self.max_bytes) for frames in iterator)
            slices = itertools.chain(*itertools.chain(*slices))
            batches = (self._create_batch(sliced) for sliced in slices)
            for batch in batches:
                if should_write_start_length:
                    write_int(SpecialLengths.START_ARROW_STREAM, stream)
                    should_write_start_length = False
                yield batch

        return ArrowStreamSerializer.dump_stream(
            self,
            init_stream_yield_batches(),
            stream,
            timely_flush_enabled=self.timely_flush_enabled,
            timely_flush_timeout_ms=self.timely_flush_timeout_ms,
        )


class DatabricksCogroupPandasUDFSerializer(CogroupPandasUDFSerializer):
    def __init__(
        self,
        timezone,
        safecheck,
        assign_cols_by_name,
        df_for_struct=False,
        max_prefetch=0,
        timely_flush_enabled=True,
        timely_flush_timeout_ms=100,
        max_bytes=-1,
    ):
        super(DatabricksCogroupPandasUDFSerializer, self).__init__(
            timezone,
            safecheck,
            assign_cols_by_name,
            df_for_struct,
            max_prefetch,
            timely_flush_enabled,
            timely_flush_timeout_ms,
        )
        self.max_bytes = max_bytes

    dump_stream = GroupUDFSerializer.dump_stream


"""
DatabricksGroupedAggPandasUDFSerializer is a subclass of GroupUDFSerializer that supports
slicing on the deserializer but not on the serializer. The slicing in the serializer is omitted
when dealing with large Arrow batches resulting from UDF evaluation. This behavior has been
present in Spark since its inception, as large Arrow batches after UDF execution are not a critical
issue for the Spark engine.
"""


class DatabricksGroupedAggPandasUDFSerializer(GroupUDFSerializer):
    def __init__(
        self,
        timezone,
        safecheck,
        assign_cols_by_name,
        max_prefetch,
        timely_flush_enabled,
        timely_flush_timeout_ms,
        max_bytes,
    ):
        super(DatabricksGroupedAggPandasUDFSerializer, self).__init__(
            timezone,
            safecheck,
            assign_cols_by_name,
            df_for_struct=False,
            max_prefetch=max_prefetch,
            timely_flush_enabled=timely_flush_enabled,
            timely_flush_timeout_ms=timely_flush_timeout_ms,
            max_bytes=max_bytes,
        )
        self.max_bytes = max_bytes

    dump_stream = ArrowStreamPandasUDFSerializer.dump_stream


class DatabricksArrowStreamGroupUDFSerializer(ArrowStreamGroupUDFSerializer):
    def load_stream(self, stream):
        """
        Flatten the struct into Arrow's record batches.
        """
        import pyarrow as pa

        should_read_more = read_int(stream) == 1
        while should_read_more:
            structs = [batch.column(0) for batch in ArrowStreamSerializer.load_stream(self, stream)]
            yield [
                pa.RecordBatch.from_arrays(struct.flatten(), schema=pa.schema(struct.type))
                for struct in structs
            ]
            should_read_more = read_int(stream) == 1
