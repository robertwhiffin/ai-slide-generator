#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2023-present Databricks, Inc.
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
from typing import TYPE_CHECKING, Union

from pyspark.databricks.sql import h3_functions as pyspark_db_h3_funcs

from pyspark.sql.connect.functions.builtin import _invoke_function_over_columns, lit


if TYPE_CHECKING:
    from pyspark.sql.connect._typing import ColumnOrName
    from pyspark.sql.connect.column import Column


def h3_h3tostring(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_h3tostring", col)


h3_h3tostring.__doc__ = pyspark_db_h3_funcs.h3_h3tostring.__doc__


def h3_stringtoh3(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_stringtoh3", col)


h3_stringtoh3.__doc__ = pyspark_db_h3_funcs.h3_stringtoh3.__doc__


def h3_resolution(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_resolution", col)


h3_resolution.__doc__ = pyspark_db_h3_funcs.h3_resolution.__doc__


def h3_isvalid(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_isvalid", col)


h3_isvalid.__doc__ = pyspark_db_h3_funcs.h3_isvalid.__doc__


def h3_ispentagon(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_ispentagon", col)


h3_ispentagon.__doc__ = pyspark_db_h3_funcs.h3_ispentagon.__doc__


def h3_toparent(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_toparent", col1, _col2)


h3_toparent.__doc__ = pyspark_db_h3_funcs.h3_toparent.__doc__


def h3_tochildren(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_tochildren", col1, _col2)


h3_tochildren.__doc__ = pyspark_db_h3_funcs.h3_tochildren.__doc__


def h3_longlatash3(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Union["ColumnOrName", int],
) -> "Column":
    _col3 = lit(col3) if isinstance(col3, int) else col3
    return _invoke_function_over_columns("h3_longlatash3", col1, col2, _col3)


h3_longlatash3.__doc__ = pyspark_db_h3_funcs.h3_longlatash3.__doc__


def h3_longlatash3string(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Union["ColumnOrName", int],
) -> "Column":
    _col3 = lit(col3) if isinstance(col3, int) else col3
    return _invoke_function_over_columns("h3_longlatash3string", col1, col2, _col3)


h3_longlatash3string.__doc__ = pyspark_db_h3_funcs.h3_longlatash3string.__doc__


def h3_kring(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_kring", col1, _col2)


h3_kring.__doc__ = pyspark_db_h3_funcs.h3_kring.__doc__


def h3_compact(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_compact", col)


h3_compact.__doc__ = pyspark_db_h3_funcs.h3_compact.__doc__


def h3_uncompact(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_uncompact", col1, _col2)


h3_uncompact.__doc__ = pyspark_db_h3_funcs.h3_uncompact.__doc__


def h3_distance(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_distance", col1, col2)


h3_distance.__doc__ = pyspark_db_h3_funcs.h3_distance.__doc__


def h3_validate(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_validate", col)


h3_validate.__doc__ = pyspark_db_h3_funcs.h3_validate.__doc__


def h3_try_validate(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_try_validate", col)


h3_try_validate.__doc__ = pyspark_db_h3_funcs.h3_try_validate.__doc__


def h3_boundaryaswkt(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_boundaryaswkt", col)


h3_boundaryaswkt.__doc__ = pyspark_db_h3_funcs.h3_boundaryaswkt.__doc__


def h3_boundaryasgeojson(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_boundaryasgeojson", col)


h3_boundaryasgeojson.__doc__ = pyspark_db_h3_funcs.h3_boundaryasgeojson.__doc__


def h3_boundaryaswkb(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_boundaryaswkb", col)


h3_boundaryaswkb.__doc__ = pyspark_db_h3_funcs.h3_boundaryaswkb.__doc__


def h3_centeraswkt(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_centeraswkt", col)


h3_centeraswkt.__doc__ = pyspark_db_h3_funcs.h3_centeraswkt.__doc__


def h3_centerasgeojson(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_centerasgeojson", col)


h3_centerasgeojson.__doc__ = pyspark_db_h3_funcs.h3_centerasgeojson.__doc__


def h3_centeraswkb(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_centeraswkb", col)


h3_centeraswkb.__doc__ = pyspark_db_h3_funcs.h3_centeraswkb.__doc__


def h3_hexring(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_hexring", col1, _col2)


h3_hexring.__doc__ = pyspark_db_h3_funcs.h3_hexring.__doc__


def h3_ischildof(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_ischildof", col1, col2)


h3_ischildof.__doc__ = pyspark_db_h3_funcs.h3_ischildof.__doc__


def h3_polyfillash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_polyfillash3", col1, _col2)


h3_polyfillash3.__doc__ = pyspark_db_h3_funcs.h3_polyfillash3.__doc__


def h3_polyfillash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_polyfillash3string", col1, _col2)


h3_polyfillash3string.__doc__ = pyspark_db_h3_funcs.h3_polyfillash3string.__doc__


def h3_try_polyfillash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_try_polyfillash3", col1, _col2)


h3_try_polyfillash3.__doc__ = pyspark_db_h3_funcs.h3_try_polyfillash3.__doc__


def h3_try_polyfillash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_try_polyfillash3string", col1, _col2)


h3_try_polyfillash3string.__doc__ = pyspark_db_h3_funcs.h3_try_polyfillash3string.__doc__


def h3_kringdistances(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_kringdistances", col1, _col2)


h3_kringdistances.__doc__ = pyspark_db_h3_funcs.h3_kringdistances.__doc__


def h3_minchild(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_minchild", col1, _col2)


h3_minchild.__doc__ = pyspark_db_h3_funcs.h3_minchild.__doc__


def h3_maxchild(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_maxchild", col1, _col2)


h3_maxchild.__doc__ = pyspark_db_h3_funcs.h3_maxchild.__doc__


def h3_pointash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_pointash3", col1, _col2)


h3_pointash3.__doc__ = pyspark_db_h3_funcs.h3_pointash3.__doc__


def h3_pointash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_pointash3string", col1, _col2)


h3_pointash3string.__doc__ = pyspark_db_h3_funcs.h3_pointash3string.__doc__


def h3_coverash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_coverash3", col1, _col2)


h3_coverash3.__doc__ = pyspark_db_h3_funcs.h3_coverash3.__doc__


def h3_try_coverash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_try_coverash3", col1, _col2)


h3_try_coverash3.__doc__ = pyspark_db_h3_funcs.h3_try_coverash3.__doc__


def h3_coverash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_coverash3string", col1, _col2)


h3_coverash3string.__doc__ = pyspark_db_h3_funcs.h3_coverash3string.__doc__


def h3_try_coverash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_try_coverash3string", col1, _col2)


h3_try_coverash3string.__doc__ = pyspark_db_h3_funcs.h3_try_coverash3string.__doc__


def h3_try_distance(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("h3_try_distance", col1, col2)


h3_try_distance.__doc__ = pyspark_db_h3_funcs.h3_try_distance.__doc__


def h3_tessellateaswkb(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_tessellateaswkb", col1, _col2)


h3_tessellateaswkb.__doc__ = pyspark_db_h3_funcs.h3_tessellateaswkb.__doc__


def h3_try_tessellateaswkb(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("h3_try_tessellateaswkb", col1, _col2)


h3_try_tessellateaswkb.__doc__ = pyspark_db_h3_funcs.h3_try_tessellateaswkb.__doc__


def _test() -> None:
    import sys
    import doctest
    from pyspark.sql import SparkSession as PySparkSession
    import pyspark.databricks.sql.connect.functions

    globs = pyspark.databricks.sql.connect.h3_functions.__dict__.copy()

    globs["spark"] = (
        PySparkSession.builder.appName("databricks.sql.connect.h3_functions tests")
        .remote("local[4]")
        .getOrCreate()
    )

    (failure_count, test_count) = doctest.testmod(
        pyspark.databricks.sql.connect.h3_functions,
        globs=globs,
        optionflags=doctest.ELLIPSIS
        | doctest.NORMALIZE_WHITESPACE
        | doctest.IGNORE_EXCEPTION_DETAIL,
    )

    globs["spark"].stop()

    if failure_count:
        sys.exit(-1)


if __name__ == "__main__":
    _test()
