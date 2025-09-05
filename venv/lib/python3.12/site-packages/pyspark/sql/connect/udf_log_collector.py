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
from typing import List, Tuple, TYPE_CHECKING

from pyspark.sql.udf_logger import LogsT, LogsParam, LogsParamValueT
from pyspark.sql.udf_log_collector import UDFLogCollector, UDFLogs

if TYPE_CHECKING:
    from pyspark.sql.dataframe import DataFrame
    from pyspark.sql.connect.session import SparkSession


class ConnectUDFLogCollector(UDFLogCollector):
    def __init__(self) -> None:
        super().__init__()
        # The max entries from workers should be used.
        self._param = LogsParam(None)
        self._value = self._param.zero(({}, None))

    @property
    def _logs(self) -> LogsT:
        return self._value[0]

    def _update(self, update: LogsParamValueT) -> None:
        with self._lock:
            self._value = self._param.addInPlace(self._value, update)


class ConnectUDFLogs(UDFLogs):
    def __init__(self, sparkSession: "SparkSession"):
        self._sparkSession = sparkSession

    @property
    def _collector(self) -> UDFLogCollector:
        return self._sparkSession._client._udf_log_collector

    def _create_dataframe(self, logs: List[Tuple], schema: str) -> "DataFrame":
        return self._sparkSession.createDataFrame(logs, schema)
