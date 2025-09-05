#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2022-present Databricks, Inc.
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
import sys
from typing import TYPE_CHECKING, Union

from pyspark import SparkContext
from pyspark.sql.column import Column
from pyspark.sql.classic.column import _to_java_column
from pyspark.sql.utils import try_remote_edge_functions

if TYPE_CHECKING:
    from pyspark.sql._typing import ColumnOrName


###################################################################################################
# Python H3 functions
###################################################################################################
@try_remote_edge_functions
def h3_h3tostring(col: "ColumnOrName") -> Column:
    """Converts an H3 cell ID to a string representing the cell ID as a hexadecimal string.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID represented as a BIGINT.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775,)], ['h3l'])
    >>> df.select(dbf.h3_h3tostring('h3l').alias('result')).collect()
    [Row(result='85283473fffffff')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_h3tostring(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_stringtoh3(col: "ColumnOrName") -> Column:
    """Converts the string representation H3 cell ID to its big integer representation.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID represented as a STRING.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('85283473fffffff',)], ['h3s'])
    >>> df.select(dbf.h3_stringtoh3('h3s').alias('result')).collect()
    [Row(result=599686042433355775)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_stringtoh3(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_resolution(col: "ColumnOrName") -> Column:
    """Returns the resolution of the H3 cell ID.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or a STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775,)], ['h3l'])
    >>> df.select(dbf.h3_resolution('h3l').alias('result')).collect()
    [Row(result=5)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_resolution(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_isvalid(col: "ColumnOrName") -> Column:
    """Returns true if the input represents a valid H3 cell ID.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A BIGINT or STRING.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775,)], ['h3l'])
    >>> df.select(dbf.h3_isvalid('h3l').alias('result')).collect()
    [Row(result=True)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_isvalid(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_ispentagon(col: "ColumnOrName") -> Column:
    """Returns true if the input H3 cell ID represents a pentagon.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or a STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(590112357393367039,)], ['h3l'])
    >>> df.select(dbf.h3_ispentagon('h3l').alias('result')).collect()
    [Row(result=True)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_ispentagon(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_toparent(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the parent H3 cell ID of the input H3 cell ID at the specified resolution.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or a STRING).
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the parent H3 cell ID that we want to return. Must be non-negative and
        smaller or equal to the resolution of the first argument.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775, 0,)], ['h3l', 'res'])
    >>> df.select(dbf.h3_toparent('h3l', 'res').alias('result')).collect()
    [Row(result=577199624117288959)]
    >>> df.select(dbf.h3_toparent('h3l', 0).alias('result')).collect()
    [Row(result=577199624117288959)]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_toparent(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_tochildren(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the children H3 cell IDs of the input H3 cell ID at the specified resolution.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or a STRING).
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the child H3 cell IDs that we want to return. Must greater or equal to
        the resolution of the first argument, and smaller than 16.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775, 6,)], ['h3l', 'res'])
    >>> df.select(dbf.h3_tochildren('h3l', 'res').alias('result')).collect()
    [Row(result=[604189641121202175, 604189641255419903, 604189641389637631, 604189641523855359, \
    604189641658073087, 604189641792290815, 604189641926508543])]
    >>> df.select(dbf.h3_tochildren('h3l', 6).alias('result')).collect()
    [Row(result=[604189641121202175, 604189641255419903, 604189641389637631, 604189641523855359, \
    604189641658073087, 604189641792290815, 604189641926508543])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_tochildren(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_longlatash3(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Union["ColumnOrName", int],
) -> Column:
    """Returns the H3 cell ID (as a BIGINT) corresponding to the provided longitude and latitude
    at the specified resolution.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The longitude (in degrees) of the point we want represent with the returned H3 cell ID.
    col2 : :class:`~pyspark.sql.Column` or str
        The latitude (in degrees) of the point we want represent with the returned H3 cell ID.
    col3 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that we want to return. Must be between 0 and 15,
        inclusive.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(100, 45, 6,)], ['lon', 'lat', 'res'])
    >>> df.select(dbf.h3_longlatash3('lon', 'lat', 'res').alias('result')).collect()
    [Row(result=604116085645508607)]
    >>> df.select(dbf.h3_longlatash3('lon', 'lat', 6).alias('result')).collect()
    [Row(result=604116085645508607)]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col3 = lit(col3) if isinstance(col3, int) else col3
    jc = sc._jvm.com.databricks.sql.functions.h3_longlatash3(
        _to_java_column(col1), _to_java_column(col2), _to_java_column(col3)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_longlatash3string(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Union["ColumnOrName", int],
) -> Column:
    """Returns the H3 cell ID (as a STRING) corresponding to the provided longitude and latitude at
    the specified resolution.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The longitude (in degrees) of the point we want represent with the returned H3 cell ID.
    col2 : :class:`~pyspark.sql.Column` or str
        The latitude (in degrees) of the point we want represent with the returned H3 cell ID.
    col3 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that we want to return. Must be between 0 and 15,
        inclusive.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(100, 45, 6,)], ['lon', 'lat', 'res'])
    >>> df.select(dbf.h3_longlatash3string('lon', 'lat', 'res').alias('result')).collect()
    [Row(result='86240610fffffff')]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col3 = lit(col3) if isinstance(col3, int) else col3
    jc = sc._jvm.com.databricks.sql.functions.h3_longlatash3string(
        _to_java_column(col1), _to_java_column(col2), _to_java_column(col3)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_kring(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the H3 cell IDs that are within (grid) distance k of the origin cell ID.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The maximum grid distance from the H3 cell ID (first argument).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775, 1,)], ['h3l', 'k'])
    >>> df.select(dbf.h3_kring('h3l', 'k').alias('result')).collect()
    [Row(result=[599686042433355775, 599686030622195711, 599686044580839423, 599686038138388479, \
    599686043507097599, 599686015589810175, 599686014516068351])]
    >>> df.select(dbf.h3_kring('h3l', 1).alias('result')).collect()
    [Row(result=[599686042433355775, 599686030622195711, 599686044580839423, 599686038138388479, \
    599686043507097599, 599686015589810175, 599686014516068351])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_kring(_to_java_column(col1), _to_java_column(col2))
    return Column(jc)


@try_remote_edge_functions
def h3_compact(col: "ColumnOrName") -> Column:
    """Compacts the input set of H3 cell IDs as best as possible.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An array of H3 cell IDs (represented as a BIGINTs or STRINGs) that we want to compact.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([([599686042433355775, 599686030622195711, 599686044580839423,
    ... 599686038138388479, 599686043507097599, 599686015589810175, 599686014516068351,
    ... 599686034917163007, 599686029548453887, 599686032769679359, 599686198125920255,
    ... 599686040285872127, 599686041359613951, 599686039212130303, 599686023106002943,
    ... 599686027400970239, 599686013442326527, 599686012368584703, 599686018811035647],)],
    ... ['h3l_array'])
    >>> df.select(dbf.h3_compact('h3l_array').alias('result')).collect()
    [Row(result=[599686030622195711, 599686015589810175, 599686014516068351, 599686034917163007, \
    599686029548453887, 599686032769679359, 599686198125920255, 599686023106002943, \
    599686027400970239, 599686013442326527, 599686012368584703, 599686018811035647, \
    595182446027210751])]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_compact(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_uncompact(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Uncompacts the input set of H3 cell IDs to the specified resolution.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An array of H3 cell IDs (represented as a BIGINTs or STRINGs) that we want to uncompact.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the uncompated H3 cell IDs.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([([599686030622195711, 599686015589810175, 599686014516068351,
    ... 599686034917163007, 599686029548453887, 599686032769679359, 599686198125920255,
    ... 599686023106002943, 599686027400970239, 599686013442326527, 599686012368584703,
    ... 599686018811035647, 595182446027210751], 5,)], ['h3l_array', 'res'])
    >>> df.select(dbf.h3_uncompact('h3l_array', 'res').alias('result')).collect()
    [Row(result=[599686030622195711, 599686015589810175, 599686014516068351, 599686034917163007, \
    599686029548453887, 599686032769679359, 599686198125920255, 599686023106002943, \
    599686027400970239, 599686013442326527, 599686012368584703, 599686018811035647, \
    599686038138388479, 599686039212130303, 599686040285872127, 599686041359613951, \
    599686042433355775, 599686043507097599, 599686044580839423])]
    >>> df.select(dbf.h3_uncompact('h3l_array', 5).alias('result')).collect()
    [Row(result=[599686030622195711, 599686015589810175, 599686014516068351, 599686034917163007, \
    599686029548453887, 599686032769679359, 599686198125920255, 599686023106002943, \
    599686027400970239, 599686013442326527, 599686012368584703, 599686018811035647, \
    599686038138388479, 599686039212130303, 599686040285872127, 599686041359613951, \
    599686042433355775, 599686043507097599, 599686044580839423])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_uncompact(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_distance(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns the grid distance between two H3 cell IDs.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).
    col2 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686030622195711, 599686015589810175,)], ['h3l1', 'h3l2'])
    >>> df.select(dbf.h3_distance('h3l1', 'h3l2').alias('result')).collect()
    [Row(result=2)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_distance(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_validate(col: "ColumnOrName") -> Column:
    """Returns the input value if it is a valid H3 cell or emits an error otherwise.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A BIGINT or STRING.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686030622195711,)], ['h3l'])
    >>> df.select(dbf.h3_validate('h3l').alias('result')).collect()
    [Row(result=599686030622195711)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_validate(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_try_validate(col: "ColumnOrName") -> Column:
    """Returns the input value if it is a valid H3 cell or None otherwise.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A BIGINT or STRING.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775,),(599686042433355776,),], ['h3l'])
    >>> df.select(dbf.h3_try_validate('h3l').alias('result')).collect()
    [Row(result=599686042433355775), Row(result=None)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_try_validate(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_boundaryaswkt(col: "ColumnOrName") -> Column:
    """Returns the boundary of an H3 cell in WKT format.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775,),], ['h3l'])
    >>> df.select(dbf.h3_boundaryaswkt('h3l').alias('result')).collect()
    [Row(result='POLYGON((-121.915080327 37.271355867,-121.862223289 37.353926451,\
-121.923549996 37.428341186,-122.037734964 37.420128678,-122.090428929 37.337556084,\
-122.029101309 37.263197975,-121.915080327 37.271355867))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_boundaryaswkt(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_boundaryasgeojson(col: "ColumnOrName") -> Column:
    """Returns the boundary of an H3 cell in GeoJSON format.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775,),], ['h3l'])
    >>> df.select(dbf.h3_boundaryasgeojson('h3l').alias('result')).collect()
    [Row(result='{"type":"Polygon","coordinates":[[[-121.915080327,37.271355867],\
[-121.862223289,37.353926451],[-121.923549996,37.428341186],[-122.037734964,37.420128678],\
[-122.090428929,37.337556084],[-122.029101309,37.263197975],[-121.915080327,37.271355867]]]}')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_boundaryasgeojson(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_boundaryaswkb(col: "ColumnOrName") -> Column:
    """Returns the boundary of an H3 cell in WKB format.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql import functions as f
    >>> df = spark.createDataFrame([(599686042433355775,),], ['h3l'])
    >>> df.select(f.hex(dbf.h3_boundaryaswkb('h3l')).alias('result')).collect()
    [Row(result='01030000000100000007000000646B13AD907A5EC0DE2BFFC9BBA24240B10697AA2E775EC0FF1D4\
2764DAD42409F4271711B7B5EC02EB34CE2D3B64240ED12E93F6A825EC0940FCAC6C6B54240B52A6B96C9855EC044ACA\
A0935AB4240409BBCCBDC815EC0CC7FA378B0A14240646B13AD907A5EC0DE2BFFC9BBA24240')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_boundaryaswkb(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_centeraswkt(col: "ColumnOrName") -> Column:
    """Returns the center of an H3 cell in WKT format.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775,),], ['h3l'])
    >>> df.select(dbf.h3_centeraswkt('h3l').alias('result')).collect()
    [Row(result='POINT(-121.976375973 37.345793375)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_centeraswkt(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_centerasgeojson(col: "ColumnOrName") -> Column:
    """Returns the center of an H3 cell in GeoJSON format.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775,),], ['h3l'])
    >>> df.select(dbf.h3_centerasgeojson('h3l').alias('result')).collect()
    [Row(result='{"type":"Point","coordinates":[-121.976375973,37.345793375]}')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_centerasgeojson(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_centeraswkb(col: "ColumnOrName") -> Column:
    """Returns the center of an H3 cell in WKB format.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql import functions as f
    >>> df = spark.createDataFrame([(599686042433355775,),], ['h3l'])
    >>> df.select(f.hex(dbf.h3_centeraswkb('h3l')).alias('result')).collect()
    [Row(result='0101000000A728A6F17C7E5EC0346612F542AC4240')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_centeraswkb(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def h3_hexring(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of H3 cell IDs that form a hollow hexagonal ring centered at the origin H3
    cell and that are at grid distance k from the origin H3 cell.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The grid distance from the H3 cell ID (first argument).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775, 1,),], ['h3l', 'k'])
    >>> df.select(dbf.h3_hexring('h3l', 'k').alias('result')).collect()
    [Row(result=[599686014516068351, 599686030622195711, 599686044580839423, 599686038138388479, \
    599686043507097599, 599686015589810175])]
    >>> df.select(dbf.h3_hexring('h3l', 1).alias('result')).collect()
    [Row(result=[599686014516068351, 599686030622195711, 599686044580839423, 599686038138388479, \
    599686043507097599, 599686015589810175])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_hexring(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_ischildof(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns true if the first H3 cell ID is a child of the second H3 cell ID.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).
    col2 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(608693241318998015, 599686042433355775,),], ['h3l1', 'h3l2'])
    >>> df.select(dbf.h3_ischildof('h3l1', 'h3l2').alias('result')).collect()
    [Row(result=True)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_ischildof(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_polyfillash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of cell IDs represented as long integers, corresponding to hexagons or
    pentagons of the specified resolution that are contained by the input areal geography.
    Containment is determined by the cell centroids: a cell is considered to cover the geography if
    the cell's centroid lies inside the areal geography.
    The expression emits an error if the geography is not areal (polygon or multipolygon) or if an
    error is found when parsing the input representation of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a geography in the WGS84 coordinate reference system in WKT or GeoJSON
        format, or a BINARY representing a geography in the WGS84 coordinate reference system in WKB
        format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(
    ... 'POLYGON((-122.4194 37.7749,-118.2437 34.0522,-74.0060 40.7128,-122.4194 37.7749))', 2),],
    ... ['wkt', 'res'])
    >>> df.select(dbf.h3_polyfillash3('wkt', 'res').alias('result')).collect()
    [Row(result=[586146350232502271, 586147449744130047, 586198577034821631, 586152397546455039, \
    586199676546449407, 586153497058082815, 586142501941805055, 586201325813891071])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_polyfillash3(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_polyfillash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of cell IDs represented as strings, corresponding to hexagons or pentagons
    of the specified resolution that are contained by the input areal geography.
    Containment is determined by the cell centroids: a cell is considered to cover the geography if
    the cell's centroid lies inside the areal geography.
    The expression emits an error if the geography is not areal (polygon or multipolygon) or if an
    error is found when parsing the input representation of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a geography in the WGS84 coordinate reference system in WKT or GeoJSON
        format, or a BINARY representing a geography in the WGS84 coordinate reference system in WKB
        format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(
    ... 'POLYGON((-122.4194 37.7749,-118.2437 34.0522,-74.0060 40.7128,-122.4194 37.7749))', 2),],
    ... ['wkt', 'res'])
    >>> df.select(dbf.h3_polyfillash3string('wkt', 'res').alias('result')).collect()
    [Row(result=['82268ffffffffff', '82269ffffffffff', '822987fffffffff', '8226e7fffffffff', \
    '822997fffffffff', '8226f7fffffffff', '822657fffffffff', '8229affffffffff'])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_polyfillash3string(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_try_polyfillash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of cell IDs represented as long integers, corresponding to hexagons or
    pentagons of the specified resolution that are contained by the input areal geography.
    Containment is determined by the cell centroids: a cell is considered to cover the geography if
    the cell's centroid lies inside the areal geography.
    The expression's value is NULL if the geography is not areal (polygon or multipolygon) or if an
    error is found when parsing the input representation of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a geography in the WGS84 coordinate reference system in WKT or GeoJSON
        format, or a BINARY representing a geography in the WGS84 coordinate reference system in WKB
        format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(
    ... 'POLYGON((-122.4194 37.7749,-118.2437 34.0522,-74.0060 40.7128,-122.4194 37.7749))', 2),],
    ... ['wkt', 'res'])
    >>> df.select(dbf.h3_try_polyfillash3('wkt', 'res').alias('result')).collect()
    [Row(result=[586146350232502271, 586147449744130047, 586198577034821631, 586152397546455039, \
    586199676546449407, 586153497058082815, 586142501941805055, 586201325813891071])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_try_polyfillash3(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_try_polyfillash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of cell IDs represented as strings, corresponding to hexagons or pentagons
    of the specified resolution that are contained by the input areal geography.
    Containment is determined by the cell centroids: a cell is considered to cover the geography if
    the cell's centroid lies inside the areal geography.
    The expression's value is NULL if the geography is not areal (polygon or multipolygon) or if an
    error is found when parsing the input representation of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a geography in the WGS84 coordinate reference system in WKT or GeoJSON
        format, or a BINARY representing a geography in the WGS84 coordinate reference system in WKB
        format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(
    ... 'POLYGON((-122.4194 37.7749,-118.2437 34.0522,-74.0060 40.7128,-122.4194 37.7749))', 2),],
    ... ['wkt', 'res'])
    >>> df.select(dbf.h3_try_polyfillash3string('wkt', 'res').alias('result')).collect()
    [Row(result=['82268ffffffffff', '82269ffffffffff', '822987fffffffff', '8226e7fffffffff', \
    '822997fffffffff', '8226f7fffffffff', '822657fffffffff', '8229affffffffff'])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_try_polyfillash3string(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_kringdistances(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns all H3 cell IDs (represented as long integers or strings) within grid distance k from
    the origin H3 cell ID, along with their distance from the origin H3 cell ID.
    More precisely, the result is an array of structs, where each struct contains an H3 cell
    id (represented as a long integer or string) and its distance from the origin H3 cell ID.
    The type for the H3 cell IDs in the output is the same as the type of the input H3 cell ID
    (first argument of the expression).

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The maximum grid distance from the H3 cell ID (first argument).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775, '85283473fffffff', 1,),],
    ... ['h3l', 'h3s', 'res'])
    >>> df.select(dbf.h3_kringdistances('h3l', 'res').alias('result')).collect()
    [Row(result=[Row(cellid=599686042433355775, distance=0), \
    Row(cellid=599686030622195711, distance=1), Row(cellid=599686044580839423, distance=1), \
    Row(cellid=599686038138388479, distance=1), Row(cellid=599686043507097599, distance=1), \
    Row(cellid=599686015589810175, distance=1), Row(cellid=599686014516068351, distance=1)])]
    >>> df.select(dbf.h3_kringdistances('h3s', 'res').alias('result')).collect()
    [Row(result=[Row(cellid='85283473fffffff', distance=0), \
    Row(cellid='85283447fffffff', distance=1), Row(cellid='8528347bfffffff', distance=1), \
    Row(cellid='85283463fffffff', distance=1), Row(cellid='85283477fffffff', distance=1), \
    Row(cellid='8528340ffffffff', distance=1), Row(cellid='8528340bfffffff', distance=1)])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_kringdistances(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_minchild(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the child of minimum value of the input H3 cell at the specified resolution.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or a STRING).
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the minimum value child cell ID that we want to return. Must be
        non-negative and larger or equal to the resolution of the first argument.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775, 10,)], ['h3l', 'res'])
    >>> df.select(dbf.h3_minchild('h3l', 'res').alias('result')).collect()
    [Row(result=622204039496499199)]
    >>> df.select(dbf.h3_minchild('h3l', 10).alias('result')).collect()
    [Row(result=622204039496499199)]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_minchild(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_maxchild(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the child of maximum value of the input H3 cell at the specified resolution.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or a STRING).
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the maximum value child cell ID that we want to return. Must be
        non-negative and larger or equal to the resolution of the first argument.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(599686042433355775, 10,)], ['h3l', 'res'])
    >>> df.select(dbf.h3_maxchild('h3l', 'res').alias('result')).collect()
    [Row(result=622204040416821247)]
    >>> df.select(dbf.h3_maxchild('h3l', 10).alias('result')).collect()
    [Row(result=622204040416821247)]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_maxchild(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_pointash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the H3 cell ID (as a BIGINT) corresponding to the provided point at the specified
    resolution.
    The expression emits an error if the geography is not a point or if an error is found when
    parsing the input representation of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a point geography in the WGS84 coordinate reference system in WKT or
        GeoJSON format, or a BINARY representing a geography in the WGS84 coordinate reference
        system in WKB format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell ID we want to compute that corresponds to the point geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(-122.4783 37.8199)', 13),], ['wkt', 'res'])
    >>> df.select(dbf.h3_pointash3('wkt', 'res').alias('result')).collect()
    [Row(result=635714569676958015)]
    >>> df.select(dbf.h3_pointash3('wkt', 13).alias('result')).collect()
    [Row(result=635714569676958015)]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_pointash3(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_pointash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the H3 cell ID (as a STRING) corresponding to the provided point at the specified
    resolution.
    The expression emits an error if the geography is not a point or if an error is found when
    parsing the input representation of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a point geography in the WGS84 coordinate reference system in WKT or
        GeoJSON format, or a BINARY representing a geography in the WGS84 coordinate reference
        system in WKB format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell ID we want to compute that corresponds to the point geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(-122.4783 37.8199)', 13),], ['wkt', 'res'])
    >>> df.select(dbf.h3_pointash3string('wkt', 'res').alias('result')).collect()
    [Row(result='8d283087022a93f')]
    >>> df.select(dbf.h3_pointash3string('wkt', 13).alias('result')).collect()
    [Row(result='8d283087022a93f')]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_pointash3string(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_coverash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of cell IDs represented as long integers, corresponding to hexagons or
    pentagons of the specified resolution that minimally cover the input linear or areal geography.
    The expression emits an error if the geography is not linear (linestring or multilinestring),
    areal (polygon or multipolygon), or if an error is found when parsing the input representation
    of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.4.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a linear or areal geography in the WGS84 coordinate reference system
        in WKT or GeoJSON format, or a BINARY representing a linear or areal geography in the WGS84
        coordinate reference system in WKB format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(
    ... 'POLYGON((-122.4194 37.7749,-118.2437 34.0522,-74.0060 40.7128,-122.4194 37.7749))', 1),],
    ... ['wkt', 'res'])
    >>> df.select(dbf.h3_coverash3('wkt', 'res').alias('result')).collect()
    [Row(result=[581650447186526207, 581672437419081727, 581698825698148351, 581707621791170559, \
    581716417884192767, 582248581512036351, 581637253046992895, 581641651093503999, \
    581646049140015103])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_coverash3(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)

@try_remote_edge_functions
def h3_try_coverash3(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of cell IDs represented as long integers, corresponding to hexagons or
    pentagons of the specified resolution that minimally cover the input linear or areal geography.
    The expression returns `None` if the geography is not linear (linestring or multilinestring),
    areal (polygon or multipolygon) or if an error is found when parsing the input. The expression
    returns an error if the input resolution is invalid.
    representation of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a linear or areal geography in the WGS84 coordinate reference system
        in WKT or GeoJSON format, or a BINARY representing a linear or areal geography in the WGS84
        coordinate reference system in WKB format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(
    ... 'POLYGON((-122.4194 37.7749,-118.2437 34.0522,-74.0060 40.7128,-122.4194 37.7749))', 1),],
    ... ['wkt', 'res'])
    >>> df.select(dbf.h3_try_coverash3('wkt', 'res').alias('result')).collect()
    [Row(result=[581650447186526207, 581672437419081727, 581698825698148351, 581707621791170559, \
    581716417884192767, 582248581512036351, 581637253046992895, 581641651093503999, \
    581646049140015103])]
    >>> df_invalid = spark.createDataFrame([('invalid input', 1),], ['wkt', 'res'])
    >>> df_invalid.select(dbf.h3_try_coverash3('wkt', 'res').alias('result')).collect()
    [Row(result=None)]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_try_coverash3(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_coverash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of cell IDs represented as strings, corresponding to hexagons or pentagons
    of the specified resolution that minimally cover the input linear or areal geography.
    The expression emits an error if the geography is not linear (linestring or multilinestring),
    areal (polygon or multipolygon), or if an error is found when parsing the input representation
    of the geography.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.4.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a linear or areal geography in the WGS84 coordinate reference system
        in WKT or GeoJSON format, or a BINARY representing a linear or areal geography in the WGS84
        coordinate reference system in WKB format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(
    ... 'POLYGON((-122.4194 37.7749,-118.2437 34.0522,-74.0060 40.7128,-122.4194 37.7749))', 1),],
    ... ['wkt', 'res'])
    >>> df.select(dbf.h3_coverash3string('wkt', 'res').alias('result')).collect()
    [Row(result=['8126fffffffffff', '81283ffffffffff', '8129bffffffffff', '812a3ffffffffff', \
    '812abffffffffff', '8148fffffffffff', '81263ffffffffff', '81267ffffffffff', '8126bffffffffff'])]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_coverash3string(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)

@try_remote_edge_functions
def h3_try_coverash3string(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of cell IDs represented as strings, corresponding to hexagons or pentagons
    of the specified resolution that minimally cover the input linear or areal geography.
    The expression returns `None` if the geography is not linear (linestring or multilinestring),
    areal (polygon or multipolygon) or if an error is found when parsing the input. The expression
    returns an error if the input resolution is invalid.
    The acceptable input representations are WKT, GeoJSON, and WKB. In the first two cases the input
    is expected to be of type STRING, whereas in the last case the input is expected to be of type
    BINARY.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a linear or areal geography in the WGS84 coordinate reference system
        in WKT or GeoJSON format, or a BINARY representing a linear or areal geography in the WGS84
        coordinate reference system in WKB format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(
    ... 'POLYGON((-122.4194 37.7749,-118.2437 34.0522,-74.0060 40.7128,-122.4194 37.7749))', 1),],
    ... ['wkt', 'res'])
    >>> df.select(dbf.h3_try_coverash3string('wkt', 'res').alias('result')).collect()
    [Row(result=['8126fffffffffff', '81283ffffffffff', '8129bffffffffff', '812a3ffffffffff', \
    '812abffffffffff', '8148fffffffffff', '81263ffffffffff', '81267ffffffffff', '8126bffffffffff'])]
    >>> df_invalid = spark.createDataFrame([('invalid input', 1),], ['wkt', 'res'])
    >>> df_invalid.select(dbf.h3_try_coverash3string('wkt', 'res').alias('result')).collect()
    [Row(result=None)]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_try_coverash3string(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)

@try_remote_edge_functions
def h3_try_distance(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns the grid distance between two H3 cell IDs of the same resolution, or NULL if the
    distance if undefined.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).
    col2 : :class:`~pyspark.sql.Column` or str
        An H3 cell ID (represented as a BIGINT or STRING).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df1 = spark.createDataFrame([(599686030622195711, 599686015589810175,)], ['h3l1', 'h3l2'])
    >>> df1.select(dbf.h3_try_distance('h3l1', 'h3l2').alias('result')).collect()
    [Row(result=2)]
    >>> df2 = spark.createDataFrame([(644730217149254377, 644877068142171537,)], ['h3l1', 'h3l2'])
    >>> df2.select(dbf.h3_try_distance('h3l1', 'h3l2').alias('result')).collect()
    [Row(result=None)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.h3_try_distance(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_tessellateaswkb(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of structs representing the chips covering geography at the specified
    resolution. More precisely, the elements of the returned array are named structs with three
    fields names "cellid", "core", and "chip":
    - The "cellid" field contains one of the H3 cells covering the input geography.
    - The "core" field determines if the boundary polygon of the H3 cell in the "cellid" field
      is contained inside the input geography (this can happen only for areal input geographies).
      If the cell is contained in the input geography the value is set to `true`, and `false`
      otherwise.
    - The "chip" field is the (Cartesian) intersection of the H3 cell polygon, corresponding to the
      H3 cell id in the "cellid" field, with the input geography, represented in WKB format.
    The set of the H3 cells ids returned as the "cellid" elements of the structs in the array is a
    minimal covering set for the input geography.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a geography in the WGS84 coordinate reference system in WKT or GeoJSON
        format, or a BINARY representing a linear or areal geography in the WGS84
        coordinate reference system in WKB format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql import functions as f
    >>> df = spark.createDataFrame([('MULTIPOINT(20 0,20 10,40 30)', 0),], ['wkt', 'res'])
    >>> chips = df.select(
    ... f.inline(dbf.h3_tessellateaswkb('wkt', 'res')).alias('cell', 'core', 'chip'))
    >>> chips.select(dbf.h3_h3tostring('cell').alias('cell'),
    ... dbf.st_astext(dbf.st_geomfromwkb('chip')).alias('wkt')).collect()
    [Row(cell='802dfffffffffff', wkt='POINT(40 30)'), \
    Row(cell='806bfffffffffff', wkt='MULTIPOINT((20 0),(20 10))')]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_tessellateaswkb(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def h3_try_tessellateaswkb(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns an array of structs representing the chips covering geography at the specified
    resolution, or null if the geometry is invalid.
    More precisely, the elements of the returned array are named structs with three
    fields names "cellid", "core", and "chip":
    - The "cellid" field contains one of the H3 cells covering the input geography.
    - The "core" field determines if the boundary polygon of the H3 cell in the "cellid" field
      is contained inside the input geography (this can happen only for areal input geographies).
      If the cell is contained in the input geography the value is set to `true`, and `false`
      otherwise.
    - The "chip" field is the (Cartesian) intersection of the H3 cell polygon, corresponding to the
      H3 cell id in the "cellid" field, with the input geography, represented in WKB format.
    The set of the H3 cells ids returned as the "cellid" elements of the structs in the array is a
    minimal covering set for the input geography.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING representing a geography in the WGS84 coordinate reference system in WKT or GeoJSON
        format, or a BINARY representing a linear or areal geography in the WGS84
        coordinate reference system in WKB format.
    col2 : :class:`~pyspark.sql.Column`, str, or int
        The resolution of the H3 cell IDs that cover the geography.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql import functions as f
    >>> df = spark.createDataFrame([('MULTIPOINT(20 0,20 10,40 30)', 0),], ['wkt', 'res'])
    >>> chips = df.select(
    ... f.inline(dbf.h3_try_tessellateaswkb('wkt', 'res')).alias('cell', 'core', 'chip'))
    >>> chips.select(dbf.h3_h3tostring('cell').alias('cell'),
    ... dbf.st_astext(dbf.st_geomfromwkb('chip')).alias('wkt')).collect()
    [Row(cell='802dfffffffffff', wkt='POINT(40 30)'), \
    Row(cell='806bfffffffffff', wkt='MULTIPOINT((20 0),(20 10))')]
    """
    from pyspark.sql.functions import lit

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.h3_try_tessellateaswkb(
        _to_java_column(col1), _to_java_column(col2)
    )
    return Column(jc)


def _test() -> None:
    import doctest
    from pyspark.sql import SparkSession
    import pyspark.databricks.sql.h3_functions

    globs = pyspark.databricks.sql.h3_functions.__dict__.copy()
    spark = (
        SparkSession.builder.master("local[4]")
        .appName("databricks.sql.h3_functions tests")
        .getOrCreate()
    )
    sc = spark.sparkContext
    globs["sc"] = sc
    globs["spark"] = spark
    (failure_count, test_count) = doctest.testmod(
        pyspark.databricks.sql.h3_functions,
        globs=globs,
        optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE,
    )
    spark.stop()
    if failure_count:
        sys.exit(-1)


if __name__ == "__main__":
    _test()
