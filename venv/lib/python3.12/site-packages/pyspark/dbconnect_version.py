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

import os

# The below are updated during build (dbconnect/python/build-dist-v2.sh)
__dbconnect_version__ = "17.1.2"

_version_unchanged = __dbconnect_version__ == "DBCONNECT_VERSION"
_dbr_version_key = "DATABRICKS_RUNTIME_VERSION"

# if the __dbconnect_version__ is not updated, then this is a DBR build. DBR version is available
# as an environment variable.
if _version_unchanged and _dbr_version_key in os.environ:
    __dbconnect_version__ = os.environ.get(_dbr_version_key)
elif _version_unchanged:
    import logging

    logging.error(
        "Could not update dbconnect version. If this is in a Databricks repl,"
        + f"the env variable {_dbr_version_key} is not set."
    )

# SASP-3899: Fix similar to above
__git_version__ = "8306fe0dc9960204b64e5efba3af532576632ece"
