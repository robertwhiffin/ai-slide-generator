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

import argparse
from databricks.connect import DatabricksSession
from pyspark.dbutils import DBUtils
from sys import version_info

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=["test"])


def test():
    print("* Checking Python version")
    if not (version_info.major >= 3 and version_info.minor >= 10):
        raise EnvironmentError(
            "Required Python version: >= 3.10 - "
            + f"Found Python version: {version_info.major}.{version_info.minor}"
        )

    print("* Creating and validating a session with the default configuration")
    spark = DatabricksSession.builder.validateSession(True).getOrCreate()

    print("* Testing the connection to the cluster - starts your cluster if it is not yet running")
    spark.version

    print("* Testing dbutils.fs")
    dbutils = DBUtils(spark)
    results = dbutils.fs.ls("/")
    if len(results) == 0:
        raise ValueError("dbutils.fs.ls failed to produce valid result")

    print("* All tests passed!")


def main():
    args = parser.parse_args()
    if args.command == "test":
        test()


if __name__ == "__main__":
    main()
