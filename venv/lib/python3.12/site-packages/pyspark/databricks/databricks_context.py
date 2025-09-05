#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2024-present Databricks, Inc.
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

from typing import Dict
from pyspark import TaskContext

"""
Provides contextual information about the Databricks environment in which the task is running.
To access the context inside a UDF, use the databricks_context module.

The module can only be used inside a Spark UDF:

#Assume that the following are imported:
>>> from pyspark.sql.functions import udf
>>> from pyspark.sql.types import StringType
>>> from pyspark.databricks import databricks_context

Retrieve the session user:
>>> udf_session_user = udf(lambda: databricks_context.session_user, StringType())
>>> spark.range(1).select(udf_session_user()).show()
'user@example.com'

Retrieve a property that doesn't exist:

>>> udf_invalid_key = udf(lambda: databricks_context.invalid_key, StringType())
>>> spark.range(1).select(udf_invalid_key()).show() # Raises AttributeError
Traceback (most recent call last):
...
AttributeError: Context 'invalid_key' is not defined.

Try to use databricks_context outside of a UDF:
>>> databricks_context.info
Traceback (most recent call last):
...
RuntimeError: databricks_context is available only within UDFs.

Try to use databricks_context when TaskContext is not available, e.g. in a subprocess:
>>> from multiprocessing import subprocess
>>> def use_databricks_context_in_subprocess():
...     from pyspark.databricks import databricks_context
...     result = subprocess.run(["python", "-c", "print(databricks_context.info)"], capture_output=True)
...     print(result.stderr.strip())
>>> failing_subprocess = udf(use_databricks_context_in_subprocess, StringType())
>>> spark.range(1).select(failing_subprocess()).show()
Traceback (most recent call last):
...
RuntimeError: databricks_context is available only within UDFs.

"""

_DATABRICKS_PREFIX = "databricks_context."


def _get_info() -> Dict[str, str]:
    """
    Retrieves all of the Databricks context information.

    Returns
    -------
    Dict[str, str]
        A dictionary of Databricks context properties.
    """
    return {
        key[len(_DATABRICKS_PREFIX) :]: value
        for key, value in _get_local_properties().items()
        if key.startswith(_DATABRICKS_PREFIX)
    }


def _get_value(key: str) -> str:
    """
    Retrieves a specific context property's value.

    Parameters
    ----------
    key : str
        The context property name.

    Returns
    -------
    str
        The value of the context property.

    Raises
    ------
    AttributeError
        If the context property is not defined
    """
    value = _get_local_properties().get(_DATABRICKS_PREFIX + key)
    if value is None:
        raise AttributeError(f"Context '{key}' is not defined.")
    return value


def _get_local_properties() -> Dict[str, str]:
    """
    Get the local properties of the current task context.

    Returns
    -------
    Dict[str, str]
        A dictionary of the local properties of the current task context. If the task context is not
        available, an empty dictionary is returned.
    """
    task_context = TaskContext.get()
    if task_context is None:
        raise RuntimeError(
            "databricks_context is available only within UDFs."
        )
    return task_context._localProperties


def __getattr__(name):
    if name == "info":
        return _get_info()
    return _get_value(name)
