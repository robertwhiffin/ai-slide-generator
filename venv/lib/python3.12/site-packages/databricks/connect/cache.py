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


import functools
from .debug import logger


class HashableDict(dict):
    # Variation of dict which can be hashed
    # _hashable_dict must not be modified after it was hashed
    def __hash__(self):
        return hash(tuple((k, self[k]) for k in sorted(self.keys())))


def cached(map_args_to_cache_id, is_stale=lambda _: False):
    """
    Decorator to cache function results.

    Parameters
    ----------
    map_args_to_cache_id:
        function transforming arguments into cache id
        map_args_to_cache_id must return object suitable as a dict key
    is_stale
        function determining if the object shouldn't be cached anymore

        By default, is_stale always returns False
    """

    def _cached(func):
        cache = dict()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            __skip_cache = kwargs.pop("__skip_cache", False)
            cache_id = map_args_to_cache_id(*args, **kwargs)
            if __skip_cache or cache_id not in cache or is_stale(cache[cache_id]):
                logger.debug("Caching: creating a new session.")
                cache[cache_id] = func(*args, **kwargs)
            else:
                logger.debug("Caching: reusing existing session.")
            return cache[cache_id]

        return wrapper

    return _cached


def cached_session(map_args_to_cache_id):
    from pyspark.sql.connect.session import SparkSession as RemoteSparkSession

    def is_session_stale(session: RemoteSparkSession) -> bool:
        return session.is_stopped

    return cached(map_args_to_cache_id, is_session_stale)
