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


import logging
from pyspark.sql.connect.client import getLogLevel


def _setup_logging():
    connect_logger = logging.getLogger('databricks.connect')
    databricks_logger = logging.getLogger('databricks')

    if getLogLevel() is not None:
        databricks_logger.setLevel(getLogLevel())

        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(fmt="%(asctime)s %(process)d %(levelname)s %(message)s")
        )
        databricks_logger.addHandler(handler)

        connect_logger.debug("Enabled debug logs for databricks-connect")

    return connect_logger


logger = _setup_logging()
