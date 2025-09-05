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

from pyspark import SparkContext
from pyspark.databricks.usage_logger import UsageLogger


def get_logger():
    """An entry point of the plug-in and return the usage logger."""
    return PandasOnSparkUsageLogger()


class PandasOnSparkUsageLogger(UsageLogger):
    def __init__(self):
        super().__init__()
        self.logger.recordImportedEvent()

    def _initialize_logger(self):
        return SparkContext._jvm.com.databricks.spark.util.PandasAPIUsageLoggingImpl()

    def log_missing(self, class_name, name, is_deprecated=False, signature=None):
        self.logger.recordMissingFunctionEvent(
            class_name, name, signature and str(signature), is_deprecated
        )
