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


class DeprecatedFuncUsageLogger:
    def __init__(self):
        from pyspark import SparkContext

        assert (
            SparkContext._jvm is not None
        ), "JVM wasn't initialised. Did you call it on executor side?"
        self.logger = SparkContext._jvm.com.databricks.spark.util.PythonUsageLoggingImpl()

    def log_deprecated(self, function_definition, class_reference):
        self.logger.recordEvent(
            self.logger.metricDefinitions().EVENT_DEPRECATED_FUNCTION(),
            {
                self.logger.tagDefinitions().TAG_FUNCTION_DEFINITION(): function_definition,
                self.logger.tagDefinitions().TAG_CLASS_REFERENCE(): class_reference,
            },
            "",
        )
