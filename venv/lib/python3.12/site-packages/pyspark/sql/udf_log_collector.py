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
from abc import ABC, abstractmethod
from itertools import chain
from threading import RLock
from typing import List, Optional, Tuple, TYPE_CHECKING

from pyspark.accumulators import (
    Accumulator,
    SpecialAccumulatorIds,
    _accumulatorRegistry,
)
from pyspark.logger.logger import SPARK_LOG_SCHEMA
from pyspark.sql.udf_logger import LogsT, LogsParam

if TYPE_CHECKING:
    from pyspark.sql.dataframe import DataFrame
    from pyspark.sql.session import SparkSession


__all__ = ["UDFLogs"]


class UDFLogCollector(ABC):
    def __init__(self) -> None:
        self._lock = RLock()

    @property
    @abstractmethod
    def _logs(self) -> LogsT:
        pass

    def list(self) -> List[int]:
        with self._lock:
            return list(self._logs.keys())

    def collect(self, id: Optional[int]) -> List[str]:
        with self._lock:
            if id is not None:
                return self._logs.get(id, [])
            else:
                return list(chain.from_iterable(self._logs.values()))

    def clear(self, id: Optional[int] = None) -> None:
        with self._lock:
            if id is not None:
                self._logs.pop(id, None)
            else:
                self._logs.clear()


class UDFLogs(ABC):
    @property
    @abstractmethod
    def _collector(self) -> UDFLogCollector:
        pass

    @abstractmethod
    def _create_dataframe(self, logs: List[Tuple], schema: str) -> "DataFrame":
        pass

    def list(self) -> List[int]:
        """
        Lists the UDF IDs that have UDF logs.

        Returns
        -------
        list of int
            The list of UDF IDs that have UDF logs.
        """
        return self._collector.list()

    def asDF(self, id: Optional[int] = None) -> "DataFrame":
        """
        Collects the UDF logs for the given UDF ID.

        Parameters
        ----------
        id : int, optional
            A UDF ID to be shown.

        Returns
        -------
        class:`DataFrame`
            The DataFrame containing UDF logs for the given ID.
        """
        from pyspark.sql.functions import from_json

        logs = self._collector.collect(id)
        return (
            self._create_dataframe([(row,) for row in logs], "json string")
            .select(from_json("json", SPARK_LOG_SCHEMA).alias("json"))
            .select("json.*")
        )

    def clear(self, id: Optional[int] = None) -> None:
        """
        Clear the UDF logs for the given UDF ID.

        Parameters
        ----------
        id : int, optional
            The UDF ID whose UDF logs should be cleared.
            If not specified, all the UDF logs will be cleared.
        """
        self._collector.clear(id)


class AccumulatorUDFLogCollector(UDFLogCollector):
    def __init__(self) -> None:
        super().__init__()
        if SpecialAccumulatorIds.SQL_UDF_LOGGER in _accumulatorRegistry:
            self._accumulator = _accumulatorRegistry[SpecialAccumulatorIds.SQL_UDF_LOGGER]
        else:
            # The max entries from workers should be used.
            param = LogsParam(None)
            self._accumulator = Accumulator(
                SpecialAccumulatorIds.SQL_UDF_LOGGER, param.zero(({}, None)), param
            )

    @property
    def _logs(self) -> LogsT:
        return self._accumulator.value[0]


class AccumulatorUDFLogs(UDFLogs):
    def __init__(self, sparkSession: "SparkSession"):
        self._sparkSession = sparkSession

    @property
    def _collector(self) -> UDFLogCollector:
        return self._sparkSession._udf_log_collector

    def _create_dataframe(self, logs: List[Tuple], schema: str) -> "DataFrame":
        return self._sparkSession.createDataFrame(logs, schema)
