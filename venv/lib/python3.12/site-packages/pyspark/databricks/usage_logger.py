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

from threading import Lock
from pyspark import SparkContext


def get_logger():
    """An entry point of the plug-in and return the usage logger singleton."""
    return _logger


class UsageLogger:
    def __init__(self):
        self._lock = Lock()
        self._logger = None
        self.enabled = True

    @property
    def logger(self):
        # Initialize the logger lazily to defer the access of _jvm from usage logger since
        # usage logger may be created before _jvm is set.
        with self._lock:
            if not self._logger:
                assert (
                    SparkContext._jvm is not None
                ), "JVM wasn't initialised. Did you call it on executor side?"
                self._logger = self._initialize_logger()
            return self._logger

    def _initialize_logger(self):
        return SparkContext._jvm.com.databricks.spark.util.PySparkAPIUsageLoggingImpl()

    def log_success(self, module_name, class_name, name, duration, signature=None):
        # Skip usage logging when _jvm is not set since logging should not block method calls.
        if not self.enabled or SparkContext._jvm is None:
            return

        self.logger.recordFunctionCallSuccessEvent(
            module_name,
            class_name,
            name,
            signature and str(signature),
            json.dumps(dict(duration=(duration * 1000))),
        )

    def log_failure(self, module_name, class_name, name, ex, duration, signature=None):
        # Skip usage logging when _jvm is not set since logging should not block method calls.
        if not self.enabled or SparkContext._jvm is None:
            return

        self.logger.recordFunctionCallFailureEvent(
            module_name,
            class_name,
            name,
            signature and str(signature),
            type(ex).__name__,
            str(ex),
            json.dumps(dict(duration=(duration * 1000))),
        )


_logger = UsageLogger()


def _configure_usage_logger():
    _logger.enabled = SparkContext._jvm.PythonUtils.isPySparkUsageLoggingEnabled(
        SparkContext._active_spark_context._jsc,
    )


SparkContext._add_after_init_hook(_configure_usage_logger)
