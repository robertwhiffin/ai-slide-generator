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
A collections of builtin avro functions
"""

from pyspark.errors import PySparkTypeError
from pyspark.sql.connect.utils import check_dependencies

check_dependencies(__name__)

from typing import Dict, Optional, TYPE_CHECKING

from pyspark.sql.avro import functions as PyAvroFunctions
from pyspark.sql.column import Column
from pyspark.sql.connect.functions.builtin import _invoke_function, _to_col, _options_to_col, lit
from pyspark.sql.connect.session import SparkSession

if TYPE_CHECKING:
    from pyspark.sql.connect._typing import ColumnOrName


def from_avro(
    # BEGIN-EDGE
    data: "ColumnOrName",
    jsonFormatSchema: Optional[str] = None,
    options: Optional[Dict[str, str]] = None,
    subject: Optional[str] = None,
    schemaRegistryAddress: Optional[str] = None,
) -> Column:
    session = SparkSession.active()
    typecheck_enabled = (
        str(session.conf.get("spark.databricks.sql.avro.pythonAvroTypecheck.enabled")).lower()
        == "true"
    )
    if typecheck_enabled:
        if not isinstance(data, (Column, str)):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={
                    "arg_name": "data",
                    "arg_type": "pyspark.sql.Column or str",
                },
            )
        if jsonFormatSchema is not None and not isinstance(jsonFormatSchema, str):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={"arg_name": "jsonFormatSchema", "arg_type": "str, optional"},
            )
        if options is not None and not isinstance(options, dict):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={"arg_name": "options", "arg_type": "dict, optional"},
            )
        if subject is not None and not isinstance(subject, str):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={"arg_name": "subject", "arg_type": "str, optional"},
            )
        if schemaRegistryAddress is not None and not isinstance(schemaRegistryAddress, str):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={"arg_name": "schemaRegistryAddress", "arg_type": "str, optional"},
            )

    if not jsonFormatSchema:
        if subject and schemaRegistryAddress:
            if options is None:
                return _invoke_function(
                    "from_avro_schema_registry",
                    _to_col(data),
                    lit(subject),
                    lit(schemaRegistryAddress),
                )
            else:
                return _invoke_function(
                    "from_avro_schema_registry",
                    _to_col(data),
                    lit(subject),
                    lit(schemaRegistryAddress),
                    _options_to_col(options),
                )
        else:
            raise ValueError(
                "Both subject and schemaRegistryAddress should be provided for Schema Registry"
            )
    else:
        # END-EDGE
        if options is None:
            return _invoke_function("from_avro", _to_col(data), lit(jsonFormatSchema))
        else:
            return _invoke_function(
                "from_avro", _to_col(data), lit(jsonFormatSchema), _options_to_col(options)
            )


from_avro.__doc__ = PyAvroFunctions.from_avro.__doc__


# BEGIN-EDGE
def to_avro(
    data: "ColumnOrName",
    jsonFormatSchema: Optional[str] = None,
    subject: Optional["ColumnOrName"] = None,
    schemaRegistryAddress: Optional[str] = None,
    options: Optional[Dict[str, str]] = None,
) -> Column:
    session = SparkSession.active()
    typecheck_enabled = (
        str(session.conf.get("spark.databricks.sql.avro.pythonAvroTypecheck.enabled")).lower()
        == "true"
    )
    if typecheck_enabled:
        if not isinstance(data, (Column, str)):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={
                    "arg_name": "data",
                    "arg_type": "pyspark.sql.Column or str",
                },
            )
        if jsonFormatSchema is not None and not isinstance(jsonFormatSchema, str):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={"arg_name": "jsonFormatSchema", "arg_type": "str, optional"},
            )
        if subject is not None and not isinstance(subject, (Column, str)):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={
                    "arg_name": "subject",
                    "arg_type": "pyspark.sql.Column or str, optional",
                },
            )
        if schemaRegistryAddress is not None and not isinstance(schemaRegistryAddress, str):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={"arg_name": "schemaRegistryAddress", "arg_type": "str, optional"},
            )
        if options is not None and not isinstance(options, dict):
            raise PySparkTypeError(
                errorClass="INVALID_TYPE",
                messageParameters={"arg_name": "options", "arg_type": "dict, optional"},
            )

    if jsonFormatSchema:
        if subject is not None and schemaRegistryAddress:
            if options is None:
                return _invoke_function(
                    "to_avro_schema_registry",
                    _to_col(data),
                    _to_col(subject),
                    lit(schemaRegistryAddress),
                    lit(jsonFormatSchema),
                )
            else:
                return _invoke_function(
                    "to_avro_schema_registry",
                    _to_col(data),
                    _to_col(subject),
                    lit(schemaRegistryAddress),
                    _options_to_col(options),
                    lit(jsonFormatSchema),
                )
        else:
            return _invoke_function(
                "to_avro",
                _to_col(data),
                lit(jsonFormatSchema),
            )
    else:
        if subject is not None and schemaRegistryAddress:
            if options is None:
                return _invoke_function(
                    "to_avro_schema_registry",
                    _to_col(data),
                    _to_col(subject),
                    lit(schemaRegistryAddress),
                )
            else:
                return _invoke_function(
                    "to_avro_schema_registry",
                    _to_col(data),
                    _to_col(subject),
                    lit(schemaRegistryAddress),
                    _options_to_col(options),
                )
        else:
            return _invoke_function(
                "to_avro",
                _to_col(data),
            )


to_avro.__doc__ = PyAvroFunctions.to_avro.__doc__


def _test() -> None:
    import os
    import sys
    from pyspark.testing.sqlutils import search_jar

    avro_jar = search_jar("connector/avro", "spark-avro", "spark-avro")
    if avro_jar is None:
        print(
            "Skipping all Avro Python tests as the optional Avro project was "
            "not compiled into a JAR. To run these tests, "
            "you need to build Spark with 'build/sbt -Pavro package' or "
            "'build/mvn -Pavro package' before running this test."
        )
        sys.exit(0)
    else:
        existing_args = os.environ.get("PYSPARK_SUBMIT_ARGS", "pyspark-shell")
        jars_args = "--jars %s" % avro_jar
        os.environ["PYSPARK_SUBMIT_ARGS"] = " ".join([jars_args, existing_args])

    import doctest
    from pyspark.sql import SparkSession as PySparkSession
    import pyspark.sql.connect.avro.functions

    globs = pyspark.sql.connect.avro.functions.__dict__.copy()
    globs["spark"] = (
        PySparkSession.builder.appName("sql.connect.avro.functions tests")
        .remote(os.environ.get("SPARK_CONNECT_TESTING_REMOTE", "local[4]"))
        .getOrCreate()
    )

    # Setup Scope for UC Testing.
    from pyspark.testing.connectutils import ReusedConnectTestCase

    ReusedConnectTestCase.update_client_for_uc(globs["spark"])

    (failure_count, test_count) = doctest.testmod(
        pyspark.sql.connect.avro.functions,
        globs=globs,
        optionflags=doctest.ELLIPSIS
        | doctest.NORMALIZE_WHITESPACE
        | doctest.IGNORE_EXCEPTION_DETAIL,
    )

    globs["spark"].stop()

    if failure_count:
        sys.exit(-1)


if __name__ == "__main__":
    _test()
