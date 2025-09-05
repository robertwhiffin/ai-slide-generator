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
from collections import defaultdict
import logging
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Union

from pyspark.accumulators import (
    AccumulatorParam,
    SpecialAccumulatorIds,
    _deserialize_accumulator,
)
from pyspark.logger.logger import JSONFormatter, PySparkLoggerBase


# Type alias for logs: Dict UDF_ID -> Log entry formatted as JSON
LogsT = Dict[int, List[str]]
# Type alias for AccumulatorParam: Tuple of LogT and max entries
LogsParamValueT = Tuple[LogsT, Optional[int]]

__all__ = ["PySparkUDFLogger"]


class LogsParam(AccumulatorParam[LogsParamValueT]):
    def __init__(self, max_entries: Optional[int]):
        """
        The `AccumulatorParam` for UDF Logging.

        Parameters
        ----------
        max_entries : int, optional
            The max entries for each udf.
            If None, tries to use the max entries from the new value.
            If it's still not available, use 0.
        """
        super().__init__()
        self._max_entries = max_entries

    def zero(self, value: LogsParamValueT) -> LogsParamValueT:
        return defaultdict(list), self._max_entries

    def addInPlace(self, logs1: LogsParamValueT, logs2: LogsParamValueT) -> LogsParamValueT:
        value1, _ = logs1
        value2, max_entries_2 = logs2
        max_entries = self._max_entries
        if max_entries is None:
            # Try to use the max_entries from the new value.
            max_entries = max_entries_2
            if max_entries is None:
                # If it's still not available, just disable.
                max_entries = 0
        for k, v in value2.items():
            if max_entries == 0:
                value1[k] = []
            else:
                value1[k].extend(v)
                if max_entries > 0:
                    value1[k] = value1[k][-max_entries:]
        return value1, max_entries


class UDFLogHandler(logging.Handler):
    def __init__(
        self, udf_id: int, max_entries: int, default_context: Optional[Dict[str, Any]]
    ) -> None:
        super().__init__()
        self._udf_id = udf_id

        param = LogsParam(max_entries)
        self._accumulator = _deserialize_accumulator(
            SpecialAccumulatorIds.SQL_UDF_LOGGER, param.zero(({}, None)), param
        )
        formatter = JSONFormatter()
        formatter.default_msec_format = "%s.%03d"
        self._formatter = formatter

        self._default_context: Dict[str, Any] = default_context or {"udf_id": udf_id}

    def emit(self, record: logging.LogRecord) -> None:
        if self._udf_id is not None:
            context = record.__dict__.get("kwargs", {})
            for k, v in self._default_context.items():
                if context.get(k) is None:
                    context[k] = v
            record.__dict__["kwargs"] = context
            msg = self._formatter.format(record)
            self._accumulator.add(({self._udf_id: [msg]}, None))


class PySparkUDFLogger(PySparkLoggerBase):
    _max_entries: ClassVar[int] = 0
    _log_level: ClassVar[Union[int, str]] = logging.WARN
    _udf_id: ClassVar[Optional[int]] = None
    _default_context: ClassVar[Optional[Dict[str, Any]]] = None

    def __init__(self, name: Optional[str] = None):
        super().__init__(name or "PySparkUDFLogger", level=self._log_level)
        if self._udf_id is not None:
            self.addHandler(UDFLogHandler(self._udf_id, self._max_entries, self._default_context))
        self.propagate = False

    @staticmethod
    def getLogger(name: Optional[str] = None) -> "PySparkUDFLogger":
        return PySparkUDFLogger(name)
