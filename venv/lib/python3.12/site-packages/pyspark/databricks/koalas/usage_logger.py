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

import json

from pyspark import SparkContext

from databricks.koalas.version import __version__


def get_logger():
    """An entry point of the plug-in and return the usage logger."""
    return KoalasUsageLogger()


class KoalasUsageLogger:
    def __init__(self):
        assert (
            SparkContext._jvm is not None
        ), "JVM wasn't initialised. Did you call it on executor side?"
        self.logger = SparkContext._jvm.com.databricks.spark.util.PythonUsageLoggingImpl()
        self.logger.recordProductEvent(
            self.logger.metricDefinitions().EVENT_KOALAS_IMPORTED(),
            {self.logger.tagDefinitions().TAG_KOALAS_VERSION(): __version__},
            "",
        )

    def log_success(self, class_name, name, duration, signature=None):
        function_or_property = (
            self.logger.tagDefinitions().TAG_KOALAS_FUNCTION()
            if signature is not None
            else self.logger.tagDefinitions().TAG_KOALAS_PROPERTY()
        )
        self.logger.recordEvent(
            self.logger.metricDefinitions().EVENT_KOALAS_FUNCTION_CALLED(),
            {
                self.logger.tagDefinitions().TAG_KOALAS_VERSION(): __version__,
                self.logger.tagDefinitions().TAG_CLASS_NAME(): class_name,
                function_or_property: "{}{}".format(name, signature or ""),
                self.logger.tagDefinitions().TAG_STATUS(): "success",
            },
            json.dumps(dict(duration=(duration * 1000))),
        )

    def log_failure(self, class_name, name, ex, duration, signature=None):
        function_or_property = (
            self.logger.tagDefinitions().TAG_KOALAS_FUNCTION()
            if signature is not None
            else self.logger.tagDefinitions().TAG_KOALAS_PROPERTY()
        )
        self.logger.recordEvent(
            self.logger.metricDefinitions().EVENT_KOALAS_FUNCTION_CALLED(),
            {
                self.logger.tagDefinitions().TAG_KOALAS_VERSION(): __version__,
                self.logger.tagDefinitions().TAG_CLASS_NAME(): class_name,
                function_or_property: "{}{}".format(name, signature or ""),
                self.logger.tagDefinitions().TAG_STATUS(): "failure",
                self.logger.tagDefinitions().TAG_ERROR(): type(ex).__name__,
                self.logger.tagDefinitions().TAG_ERROR_MESSAGE(): str(ex),
            },
            json.dumps(dict(duration=(duration * 1000))),
        )

    def log_missing(self, class_name, name, is_deprecated=False, signature=None):
        function_or_property = (
            self.logger.tagDefinitions().TAG_KOALAS_FUNCTION()
            if signature is not None
            else self.logger.tagDefinitions().TAG_KOALAS_PROPERTY()
        )
        self.logger.recordEvent(
            self.logger.metricDefinitions().EVENT_KOALAS_FUNCTION_CALLED(),
            {
                self.logger.tagDefinitions().TAG_KOALAS_VERSION(): __version__,
                self.logger.tagDefinitions().TAG_CLASS_NAME(): class_name,
                function_or_property: "{}{}".format(name, signature or ""),
                self.logger.tagDefinitions().TAG_STATUS(): "deprecated"
                if is_deprecated
                else "missing",
            },
            "",
        )
