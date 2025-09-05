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

"""
A set of memory-related helpers.
"""

import ctypes
import gc
import os

import psutil


def malloc_trim():
    ctypes.CDLL("libc.so.6").malloc_trim(0)


def get_used_memory():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss


def clear_memory():
    gc.collect()
    malloc_trim()
