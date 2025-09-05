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
import sys
from typing import TYPE_CHECKING, Optional, Union

from pyspark import SparkContext
from pyspark.sql.column import Column
from pyspark.sql.classic.column import _to_java_column
from pyspark.sql.utils import try_remote_edge_functions

if TYPE_CHECKING:
    from pyspark.sql._typing import ColumnOrName

to_java_column = _to_java_column

###################################################################################################
# Python ST functions
###################################################################################################


@try_remote_edge_functions
def st_addpoint(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Union["ColumnOrName", int] = -1
) -> Column:
    """Adds a new point to the n-th position in the input linestring GEOGRAPHY or GEOMETRY.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value representing a linestring.
    col2 : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value representing a point.
    col3 : :class:`~pyspark.sql.Column` or int, optional
        An optional 1-based position in the linestring where the new point should be added.
        Default value is -1.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)','POINT(7 8)',)], ['wkt1', 'wkt2'])
    >>> df.select(dbf.st_astext(dbf.st_addpoint(dbf.st_geogfromtext('wkt1'), dbf.st_geogfromtext('wkt2'), 3)).alias('result')).collect()  # noqa
    [Row(result='LINESTRING(1 2,3 4,7 8)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)','POINT(7 8)',)], ['wkt1', 'wkt2'])
    >>> df.select(dbf.st_asewkt(dbf.st_addpoint(dbf.st_geogfromtext('wkt1'), dbf.st_geogfromtext('wkt2'))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;LINESTRING(1 2,3 4,7 8)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING ZM (1 2 3 4,5 6 7 8)','POINT M (0 9 99)',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_addpoint(dbf.st_geogfromtext('wkt1'), dbf.st_geogfromtext('wkt2'), -1)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;LINESTRING ZM (1 2 3 4,5 6 7 8,0 9 0 99)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col3 = lit(col3) if isinstance(col3, int) else col3
    jc = sc._jvm.com.databricks.sql.functions.st_addpoint(
        to_java_column(col1), to_java_column(col2), to_java_column(col3)
    )
    return Column(jc)


@try_remote_edge_functions
def st_area(col: "ColumnOrName") -> Column:
    """Returns the area of the input geography or geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    If the input is a geometry, Cartesian length is returned (in the unit of the input coordinates).
    If the input is a geography, length on the WGS84 spheroid is returned (expressed in sq. meters).
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions.builtin import round
    >>> df = spark.createDataFrame([('POLYGON((0 0,50 0,50 50,0 50,0 0),(20 20,25 30,30 20,20 20))',)], ['wkt'])  # noqa
    >>> df.select(round(dbf.st_area(dbf.st_geogfromtext('wkt')) / 1e9, 2).alias('result')).collect()
    [Row(result=27228.52)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,50 0,50 50,0 50,0 0),(20 20,25 30,30 20,20 20))',)], ['wkt'])  # noqa
    >>> df.select(dbf.st_area(dbf.st_geomfromtext('wkt', 4326)).alias('result')).collect()
    [Row(result=2450.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_area(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_asbinary(
    col1: "ColumnOrName",
    col2: Optional["ColumnOrName"] = None
) -> Column:
    """Returns the input GEOGRAPHY or GEOMETRY value in WKB format.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A geospatial value, either a GEOGRAPHY or GEOMETRY.
    col2 : :class:`~pyspark.sql.Column` or str, optional
        The optional endianness of the output WKB, 'NDR' for little-endian (default) or 'XDR' for
        big-endian.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)',)], ['wkt'])
    >>> df.select(hex(dbf.st_asbinary(dbf.st_geogfromtext('wkt'))).alias('result')).collect()
    [Row(result='010200000002000000000000000000F03F000000000000004000000000000008400000000000001040')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)', 'NDR',)], ['wkt', 'e'])
    >>> df.select(hex(dbf.st_asbinary(dbf.st_geogfromtext('wkt'), df.e)).alias('result')).collect()
    [Row(result='010200000002000000000000000000F03F000000000000004000000000000008400000000000001040')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)',)], ['wkt'])
    >>> df.select(hex(dbf.st_asbinary(dbf.st_geogfromtext('wkt'), 'XDR')).alias('result')).collect()
    [Row(result='0000000002000000023FF0000000000000400000000000000040080000000000004010000000000000')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col2 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_asbinary(
            to_java_column(col1)
        )
    else:
        col2 = lit(col2) if isinstance(col2, str) else col2
        jc = sc._jvm.com.databricks.sql.functions.st_asbinary(
            to_java_column(col1), to_java_column(col2)
        )
    return Column(jc)


@try_remote_edge_functions
def st_asewkb(
    col1: "ColumnOrName",
    col2: Optional["ColumnOrName"] = None
) -> Column:
    """Returns the input GEOMETRY value in EWKB format.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str, optional
        The optional endianness of the output EWKB, 'NDR' for little-endian (default) or 'XDR' for
        big-endian.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)',)], ['wkt'])
    >>> df.select(hex(dbf.st_asewkb(dbf.st_geomfromtext('wkt'))).alias('result')).collect()
    [Row(result='010200000002000000000000000000F03F000000000000004000000000000008400000000000001040')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)', 'NDR',)], ['wkt', 'e'])
    >>> df.select(hex(dbf.st_asewkb(dbf.st_geomfromtext('wkt'), df.e)).alias('result')).collect()
    [Row(result='010200000002000000000000000000F03F000000000000004000000000000008400000000000001040')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)',)], ['wkt'])
    >>> df.select(hex(dbf.st_asewkb(dbf.st_geomfromtext('wkt'), 'XDR')).alias('result')).collect()
    [Row(result='0000000002000000023FF0000000000000400000000000000040080000000000004010000000000000')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col2 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_asewkb(
            to_java_column(col1)
        )
    else:
        col2 = lit(col2) if isinstance(col2, str) else col2
        jc = sc._jvm.com.databricks.sql.functions.st_asewkb(
            to_java_column(col1), to_java_column(col2)
        )
    return Column(jc)


@try_remote_edge_functions
def st_aswkb(
    col1: "ColumnOrName",
    col2: Optional["ColumnOrName"] = None
) -> Column:
    """Returns the input GEOGRAPHY or GEOMETRY value in WKB format.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A geospatial value, either a GEOGRAPHY or GEOMETRY.
    col2 : :class:`~pyspark.sql.Column` or str, optional
        The optional endianness of the output WKB, 'NDR' for little-endian (default) or 'XDR' for
        big-endian.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)',)], ['wkt'])
    >>> df.select(hex(dbf.st_aswkb(dbf.st_geogfromtext('wkt'))).alias('result')).collect()
    [Row(result='010200000002000000000000000000F03F000000000000004000000000000008400000000000001040')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)', 'NDR',)], ['wkt', 'e'])
    >>> df.select(hex(dbf.st_aswkb(dbf.st_geogfromtext('wkt'), df.e)).alias('result')).collect()
    [Row(result='010200000002000000000000000000F03F000000000000004000000000000008400000000000001040')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import hex
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)',)], ['wkt'])
    >>> df.select(hex(dbf.st_aswkb(dbf.st_geogfromtext('wkt'), 'XDR')).alias('result')).collect()
    [Row(result='0000000002000000023FF0000000000000400000000000000040080000000000004010000000000000')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col2 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_aswkb(
            to_java_column(col1)
        )
    else:
        col2 = lit(col2) if isinstance(col2, str) else col2
        jc = sc._jvm.com.databricks.sql.functions.st_aswkb(
            to_java_column(col1), to_java_column(col2)
        )
    return Column(jc)


@try_remote_edge_functions
def st_asewkt(col: "ColumnOrName") -> Column:
    """Returns the input GEOGRAPHY or GEOMETRY value in EWKT format.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A geospatial value, either a GEOGRAPHY or GEOMETRY.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (2.718281 3.141592 100)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_geogfromtext('wkt')).alias('result')).collect()
    [Row(result='SRID=4326;POINT Z (2.718281 3.141592 100)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_asewkt(
        to_java_column(col)
    )
    return Column(jc)


@try_remote_edge_functions
def st_asgeojson(col: "ColumnOrName") -> Column:
    """Returns the input GEOGRAPHY or GEOMETRY value in GeoJSON format.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A geospatial value, either a GEOGRAPHY or GEOMETRY.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (2.718281 3.141592 100)',)], ['wkt'])
    >>> df.select(dbf.st_asgeojson(dbf.st_geogfromtext('wkt')).alias('result')).collect()
    [Row(result='{"type":"Point","coordinates":[2.718281,3.141592,100]}')]
    >>> from pyspark.databricks.sql import functions as dbf
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_asgeojson(
        to_java_column(col)
    )
    return Column(jc)


@try_remote_edge_functions
def st_astext(col: "ColumnOrName") -> Column:
    """Returns the input GEOGRAPHY or GEOMETRY value in WKT format.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A geospatial value, either a GEOGRAPHY or GEOMETRY.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (2.718281 3.141592 100)',)], ['wkt'])
    >>> df.select(dbf.st_astext(dbf.st_geogfromtext('wkt')).alias('result')).collect()
    [Row(result='POINT Z (2.718281 3.141592 100)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_astext(
        to_java_column(col)
    )
    return Column(jc)


@try_remote_edge_functions
def st_aswkt(col: "ColumnOrName") -> Column:
    """Returns the input GEOGRAPHY or GEOMETRY value in WKT format.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A geospatial value, either a GEOGRAPHY or GEOMETRY.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (2.718281 3.141592 100)',)], ['wkt'])
    >>> df.select(dbf.st_aswkt(dbf.st_geogfromtext('wkt')).alias('result')).collect()
    [Row(result='POINT Z (2.718281 3.141592 100)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_aswkt(
        to_java_column(col)
    )
    return Column(jc)


@try_remote_edge_functions
def st_buffer(col1: "ColumnOrName", col2: Union["ColumnOrName", float]) -> Column:
    """Returns the buffer of the input geometry using the specified radius.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or float
        Radius of the buffer. The unit of the radius are those of the coordinate reference system
        of the geometry.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(0 0)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_envelope(dbf.st_buffer(dbf.st_geomfromtext('wkt', 4326), 1.0))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POLYGON((-1 -1,-1 1,1 1,1 -1,-1 -1))')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, float) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_buffer(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_centroid(col: "ColumnOrName") -> Column:
    """Returns the centroid of the input geometry as a 2D point geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((1 0, 0.5 0.866, -0.5 0.866, -1 0, -0.5 -0.866, 0.5 -0.866, 1 0))',)], ['wkt']) # noqa
    >>> df.select(dbf.st_astext(dbf.st_centroid(dbf.st_geomfromtext('wkt'))).alias('result')).collect()
    [Row(result='POINT(0 0)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_centroid(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_concavehull(
    col1: "ColumnOrName",
    col2: Union["ColumnOrName", float],
    col3: Optional[Union["ColumnOrName", bool]] = None
) -> Column:
    """Returns the concave hull of the input geometry as a geometry using the specified length
    ratio.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or float
        A DOUBLE value between 0 and 1, inclusive, representing the length ratio used to compute
        the concave hull.
    col3 : :class:`~pyspark.sql.Column` or bool
        An optional BOOLEAN value, indicating whether the output geometry, if a polygon, is allowed
        to have holes. The default value is False.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(0 0,10 0,10 10,0 10,1 1,1 5,1 9,5 1,9 9,9 1,9 5,5 9)', 0.8)], ['wkt','ratio'])  # noqa
    >>> df.select(dbf.st_astext(dbf.st_concavehull(dbf.st_geomfromtext('wkt'), 'ratio')).alias('result')).collect()  # noqa
    [Row(result='POLYGON((0 0,1 5,0 10,5 9,10 10,9 5,10 0,5 1,0 0))')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, float) else col2
    if col3 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_concavehull(
            to_java_column(col1), to_java_column(col2)
        )
    else:
        col3 = lit(col3) if isinstance(col3, bool) else col3
        jc = sc._jvm.com.databricks.sql.functions.st_concavehull(
            to_java_column(col1), to_java_column(col2), to_java_column(col3)
        )
    return Column(jc)


@try_remote_edge_functions
def st_contains(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns `true` if the first geometry contains the second geometry. Geometry collections are
    not supported.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,10 0,0 10,0 0))','POINT(1 1)',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_contains(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect() # noqa
    [Row(result=True)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,10 0,0 10,0 0))','POINT(5 6)',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_contains(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect() # noqa
    [Row(result=False)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_contains(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_convexhull(col: "ColumnOrName") -> Column:
    """Returns the convex hull of the input geometry as a geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,20 0,20 10,15 5,5 10,0 25,0 0))',)], ['wkt'])
    >>> df.select(dbf.st_astext(dbf.st_convexhull(dbf.st_geomfromtext('wkt'))).alias('result')).collect()
    [Row(result='POLYGON((0 0,0 25,20 10,20 0,0 0))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_convexhull(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_covers(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns `true` if the first geometry covers the second geometry. Geometry collections are
    not supported.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,10 0,0 10,0 0))','POINT(1 1)',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_covers(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect()
    [Row(result=True)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,10 0,0 10,0 0))','POINT(5 6)',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_covers(dbf.st_geomfromtext('wkt1', 4326), dbf.st_geomfromtext('wkt2', 4326)).alias('result')).collect()
    [Row(result=False)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_covers(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_difference(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns the point-set different of the two input geometries as a 2D geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(EMPTY,4 3,5 6,-1 8)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_difference(dbf.st_geomfromtext('wkt1', 4326), dbf.st_geomfromtext('wkt2', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;MULTIPOINT((-1 8),(5 6))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_difference(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_dimension(col: "ColumnOrName") -> Column:
    """Returns the topological dimension of the 2D projection of the input geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(EMPTY,-1 0,EMPTY)',)], ['wkt'])
    >>> df.select(dbf.st_dimension(dbf.st_geomfromtext('wkt', 4326)).alias('result')).collect()
    [Row(result=0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(-1 0,0 -1,1 0,0 1,-1 0)',)], ['wkt'])
    >>> df.select(dbf.st_dimension(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=1)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOLYGON(EMPTY,((-1 0,0 -1,1 0,0 1,-1 0)))',)], ['wkt'])
    >>> df.select(dbf.st_dimension(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=2)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import unhex
    >>> df = spark.createDataFrame([('0107000020e610000000000000',)], ['ewkb'])
    >>> df.select(dbf.st_dimension(dbf.st_geomfromewkb(unhex('ewkb'))).alias('result')).collect()
    [Row(result=0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_dimension(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_disjoint(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns `true` if the two geometries are disjoint. Geometry collections are not supported.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(1 1)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_disjoint(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect()
    [Row(result=False)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(5 6)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_disjoint(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect()
    [Row(result=True)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_disjoint(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_distance(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns the 2D Cartesian distance between the two input geometries. The units of the result
    are those of the coordinates of the input geometries.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(0 0)','LINESTRING(-10 10,20 10)',)], ['wkt1', 'wkt2'])
    >>> df.select(dbf.st_distance(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect() # noqa
    [Row(result=10.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_distance(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_distancesphere(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns the spherical distance (in meters) between two point geometries, measured on a
    sphere whose radius is the mean radius of the WGS84 ellipsoid.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value. The coordinates of the two
    point geometries are expected to be longitudes and latitudes in degrees, in that order.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions.builtin import round
    >>> df = spark.createDataFrame([('POINT(2 3)','POINT ZM (6 7 23 1000)',)], ['wkt1', 'wkt2'])
    >>> df.select(round(dbf.st_distancesphere(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')), 3).alias('result')).collect() # noqa
    [Row(result=627753.245)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_distancesphere(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_distancespheroid(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns the geodesic distance (in meters) between two point geometries on the WGS84
    ellipsoid.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value. The coordinates of the two
    point geometries are expected to be longitudes and latitudes in degrees, in that order.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions.builtin import round
    >>> df = spark.createDataFrame([('POINT(2 3)','POINT ZM (6 7 23 1000)',)], ['wkt1', 'wkt2'])
    >>> df.select(round(dbf.st_distancespheroid(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')), 3).alias('result')).collect() # noqa
    [Row(result=626380.599)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_distancespheroid(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_dwithin(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Union["ColumnOrName", float]
) -> Column:
    """Returns `true` iff the 2D Cartesian distance between the two input geometries is smaller than
    or equal to the input distance. The units of the distance are those of the coordinates of the
    input geometries.

    .. versionadded:: 4.0.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.
    col3 : :class:`~pyspark.sql.Column` or float
        The distance threshold.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(0 0)','LINESTRING(-10 10,20 10)')], ['wkt1', 'wkt2'])
    >>> df.select(dbf.st_dwithin(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2'), 10.0).alias('result')).collect() # noqa
    [Row(result=True)]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col3 = lit(col3) if isinstance(col3, float) else col3
    jc = sc._jvm.com.databricks.sql.functions.st_dwithin(
        to_java_column(col1), to_java_column(col2), to_java_column(col3)
    )
    return Column(jc)


@try_remote_edge_functions
def st_endpoint(col: "ColumnOrName") -> Column:
    """Returns the last point of the input linestring, or NULL if it doesn't exist.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value representing a linestring.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4,5 6)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_endpoint(dbf.st_geogfromtext('wkt'))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POINT(5 6)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING ZM (1 2 3 4,5 6 7 8)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_endpoint(dbf.st_geomfromtext('wkt', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POINT ZM (5 6 7 8)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_endpoint(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_envelope(col: "ColumnOrName") -> Column:
    """Returns the 2D Cartesian axis-aligned minimum bounding box (envelope) of the input
    non-empty geometry, as a geometry. Empty input geometries are returned as is.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((-1 0,0 -1,1 0,0 1,-1 0))',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_envelope(dbf.st_geomfromtext('wkt', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POLYGON((-1 -1,-1 1,1 1,1 -1,-1 -1))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_envelope(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_envelope_agg(col: "ColumnOrName") -> Column:
    """Returns the envelope of all the geometries in the column, or NULL if
       the column has zero rows, or contains only NULL values.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(EMPTY,4 3,5 6,-1 8)',), ('POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_envelope_agg(dbf.st_geomfromtext('wkt', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POLYGON((-1 0,-1 10,10 10,10 0,-1 0))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_envelope_agg(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_equals(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns `true` if the two geometries are geometrically equal. Geometry collections are not
    supported.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(1 1)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_equals(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect()
    [Row(result=False)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,10 0,0 10,0 0))','POLYGON((5 0,10 0,0 10,0 0,5 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_equals(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect()
    [Row(result=True)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_equals(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_flipcoordinates(col: "ColumnOrName") -> Column:
    """Swaps X and Y coordinates of the input geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4,5 6,7 8)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_flipcoordinates(dbf.st_geomfromtext('wkt', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;LINESTRING(2 1,4 3,6 5,8 7)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_flipcoordinates(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geogfromgeojson(col: "ColumnOrName") -> Column:
    """Parses the GeoJSON description and returns the corresponding GEOGRAPHY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value in GeoJSON format, representing a GEOGRAPHY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('{"type":"Polygon","coordinates":[[[0,0],[5,6],[7,-8],[0,0]]]}',)], ['geojson'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_geogfromgeojson('geojson')).alias('result')).collect()
    [Row(result='SRID=4326;POLYGON((0 0,5 6,7 -8,0 0))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_geogfromgeojson(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geogfromtext(col: "ColumnOrName") -> Column:
    """Parses the WKT description and returns the corresponding GEOGRAPHY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value in WKT format, representing a GEOGRAPHY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,5 6,7 -8,0 0))',)], ['wkt'])
    >>> df.select(dbf.st_astext(dbf.st_geogfromtext('wkt')).alias('result')).collect()
    [Row(result='POLYGON((0 0,5 6,7 -8,0 0))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_geogfromtext(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geogfromwkb(col: "ColumnOrName") -> Column:
    """Parses the input WKB description and returns the corresponding GEOGRAPHY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A BINARY value in WKB format, representing a GEOGRAPHY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('0103000000010000000400000000000000000000000000000000000000000000000000144000000000000018400000000000001c4000000000000020c000000000000000000000000000000000'),)], ['wkb'])  # noqa
    >>> df.select(dbf.st_astext(dbf.st_geogfromwkb('wkb')).alias('result')).collect()
    [Row(result='POLYGON((0 0,5 6,7 -8,0 0))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_geogfromwkb(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geogfromwkt(col: "ColumnOrName") -> Column:
    """Parses the WKT description and returns the corresponding GEOGRAPHY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING in WKT format, representing a geography value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,5 6,7 -8,0 0))',)], ['wkt'])
    >>> df.select(dbf.st_astext(dbf.st_geogfromwkt('wkt')).alias('result')).collect()
    [Row(result='POLYGON((0 0,5 6,7 -8,0 0))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_geogfromwkt(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geohash(
    col1: "ColumnOrName",
    col2: Optional[Union["ColumnOrName", int]] = None
) -> Column:
    """Returns the geohash of the input GEOMETRY.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or int, optional
        The optional precision (number of significant digits) of the output geohash.
        Must be non-negative.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(-122.4261475 37.77374268)',)], ['wkt'])
    >>> df.select(dbf.st_geohash(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result='9q8yyhebpbpb')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(-122.4261475 37.77374268)',)], ['wkt'])
    >>> df.select(dbf.st_geohash(dbf.st_geomfromtext('wkt'), 6).alias('result')).collect()
    [Row(result='9q8yyh')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col2 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_geohash(
            to_java_column(col1)
        )
    else:
        col2 = lit(col2) if isinstance(col2, int) else col2
        jc = sc._jvm.com.databricks.sql.functions.st_geohash(
            to_java_column(col1), to_java_column(col2)
        )
    return Column(jc)


@try_remote_edge_functions
def st_geometryn(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the 1-based n-th element of the input multi geometry, or NULL if it doesn't exist.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or int
        The 1-based index of the geometry to return.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('GEOMETRYCOLLECTION(POINT(4 5),LINESTRING(10 3,24 37,44 85))',)], ['wkt'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_geometryn(dbf.st_geomfromtext('wkt', 4326), 2)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;LINESTRING(10 3,24 37,44 85)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOLYGON(EMPTY,((0 0,10 0,0 10,0 0),(1 1,9 1,1 9,1 1)))',)], ['wkt'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_geometryn(dbf.st_geomfromtext('wkt'), 2)).alias('result')).collect()  # noqa
    [Row(result='POLYGON((0 0,10 0,0 10,0 0),(1 1,9 1,1 9,1 1))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(1 2)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_geometryn(dbf.st_geomfromtext('wkt'), 1)).alias('result')).collect()
    [Row(result='POINT(1 2)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_geometryn(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_geometrytype(col: "ColumnOrName") -> Column:
    """Returns the type of the input GEOGRAPHY or GEOMETRY value as a string.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(4 5)',)], ['wkt'])
    >>> df.select(dbf.st_geometrytype(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result='ST_Point')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_geometrytype(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geomfromewkb(col: "ColumnOrName") -> Column:
    """Parses the input EWKB description and returns the corresponding GEOMETRY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A BINARY value in EWKB format, representing a GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('0103000020E6100000010000000400000000000000000000000000000000000000000000000000144000000000000018400000000000001C4000000000000020C000000000000000000000000000000000'),)], ['ewkb'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_geomfromewkb('ewkb')).alias('result')).collect()
    [Row(result='SRID=4326;POLYGON((0 0,5 6,7 -8,0 0))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_geomfromewkb(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geomfromgeohash(col: "ColumnOrName") -> Column:
    """Returns the geohash grid box corresponding to the input geohash value as a 2D polygon
    geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value representing a geohash value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('9q8yyh',)], ['geohash'])
    >>> df.select(dbf.st_astext(dbf.st_geomfromgeohash('geohash')).alias('result')).collect()
    [Row(result='POLYGON((-122.431640625 37.77099609375,-122.431640625 37.7764892578125,-122.420654296875 37.7764892578125,-122.420654296875 37.77099609375,-122.431640625 37.77099609375))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_geomfromgeohash(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geomfromgeojson(col: "ColumnOrName") -> Column:
    """Parses the GeoJSON description and returns the corresponding GEOMETRY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value in GeoJSON format, representing a GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('{"type":"LineString","coordinates":[[5,6],[7,-8]]}',)], ['geojson'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_geomfromgeojson('geojson')).alias('result')).collect()
    [Row(result='SRID=4326;LINESTRING(5 6,7 -8)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_geomfromgeojson(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_geomfromtext(
    col1: "ColumnOrName",
    col2: Optional[Union["ColumnOrName", int]] = None
) -> Column:
    """Parses the WKT description and returns the corresponding GEOMETRY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING value in WKT format, representing a GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or int, optional
        The optional SRID value of the geometry. Default is 0.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(5 6,7 -8)',)], ['wkt'])
    >>> df.select(dbf.st_astext(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result='LINESTRING(5 6,7 -8)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(5 6,7 -8)', 3857,)], ['wkt', 'srid'])
    >>> df.select(dbf.st_astext(dbf.st_geomfromtext('wkt', 'srid')).alias('result')).collect()
    [Row(result='LINESTRING(5 6,7 -8)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col2 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_geomfromtext(
            to_java_column(col1)
        )
    else:
        col2 = lit(col2) if isinstance(col2, int) else col2
        jc = sc._jvm.com.databricks.sql.functions.st_geomfromtext(
            to_java_column(col1), to_java_column(col2)
        )
    return Column(jc)


@try_remote_edge_functions
def st_geomfromwkb(
    col1: "ColumnOrName",
    col2: Optional[Union["ColumnOrName", int]] = None
) -> Column:
    """Parses the input WKB description and returns the corresponding GEOMETRY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A BINARY value in WKB format, representing a GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or int, optional
        The optional SRID value of the geometry. Default is 0.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('010200000002000000000000000000144000000000000018400000000000001c4000000000000020c0'),)], ['wkb'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_geomfromwkb('wkb')).alias('result')).collect()
    [Row(result='LINESTRING(5 6,7 -8)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('010200000002000000000000000000144000000000000018400000000000001c4000000000000020c0'), 4326,)], ['wkb', 'srid'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_geomfromwkb('wkb', 'srid')).alias('result')).collect()
    [Row(result='SRID=4326;LINESTRING(5 6,7 -8)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col2 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_geomfromwkb(
            to_java_column(col1)
        )
    else:
        col2 = lit(col2) if isinstance(col2, int) else col2
        jc = sc._jvm.com.databricks.sql.functions.st_geomfromwkb(
            to_java_column(col1), to_java_column(col2)
        )
    return Column(jc)


@try_remote_edge_functions
def st_geomfromwkt(
    col1: "ColumnOrName",
    col2: Optional[Union["ColumnOrName", int]] = None
) -> Column:
    """Parses the WKT description and returns the corresponding GEOMETRY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A STRING in WKT format, representing a geometry value.
    col2 : :class:`~pyspark.sql.Column` or int, optional
        The optional SRID of the geometry. Default is 0.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(5 6,7 -8)',)], ['wkt'])
    >>> df.select(dbf.st_astext(dbf.st_geomfromwkt('wkt')).alias('result')).collect()
    [Row(result='LINESTRING(5 6,7 -8)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(5 6,7 -8)', 3857,)], ['wkt', 'srid'])
    >>> df.select(dbf.st_astext(dbf.st_geomfromwkt('wkt', 'srid')).alias('result')).collect()
    [Row(result='LINESTRING(5 6,7 -8)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col2 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_geomfromwkt(
            to_java_column(col1)
        )
    else:
        col2 = lit(col2) if isinstance(col2, int) else col2
        jc = sc._jvm.com.databricks.sql.functions.st_geomfromwkt(
            to_java_column(col1), to_java_column(col2)
        )
    return Column(jc)


@try_remote_edge_functions
def st_intersection(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns the point-set intersection of the two input geometries as a 2D geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(EMPTY,4 3,5 6,-1 8)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_intersection(dbf.st_geomfromtext('wkt1', 4326), dbf.st_geomfromtext('wkt2', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POINT(4 3)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_intersection(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_intersects(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns `true` if the two geometries intersect. Geometry collections are not supported.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(1 1)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_intersects(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect() # noqa
    [Row(result=True)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(5 6)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_intersects(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect() # noqa
    [Row(result=False)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_intersects(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_isempty(col: "ColumnOrName") -> Column:
    """Returns true if the input GEOGRAPHY or GEOMETRY value does not contain any non-empty points.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(10 34,44 57,EMPTY)',)], ['wkt'])
    >>> df.select(dbf.st_isempty(dbf.st_geomfromwkt('wkt')).alias('result')).collect()
    [Row(result=False)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_isempty(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_isvalid(col: "ColumnOrName") -> Column:
    """Returns true if the input geometry is a valid geometry in the OGC sense.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt'])
    >>> df.select(dbf.st_isvalid(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=True)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_isvalid(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_length(col: "ColumnOrName") -> Column:
    """Returns the length of the input geometry or geography value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    If the input is a geometry, Cartesian length is returned (in the unit of the input coordinates).
    If the input is a geography, length on the WGS84 spheroid is returned (expressed in meters).
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions.builtin import round
    >>> df = spark.createDataFrame([('LINESTRING(10 34,44 57,30 24)',)], ['wkt'])
    >>> df.select(round(dbf.st_length(dbf.st_geomfromtext('wkt')), 3).alias('result')).collect()
    [Row(result=76.896)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_length(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_m(col: "ColumnOrName") -> Column:
    """Returns the M coordinate of the input point geometry, or NULL if the input point geometry is
    empty or if it does not have an M coordinate.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT M (1 2 4)',)], ['wkt'])
    >>> df.select(dbf.st_m(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=4.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT ZM (1 2 3 4)',)], ['wkt'])
    >>> df.select(dbf.st_m(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=4.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_m(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_makeline(col: "ColumnOrName") -> Column:
    """Returns a linestring geometry whose points are the non-empty points of the geometries in the
    input array of geometries, which are expected to be points, linestrings, or multipoints.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        An array of GEOMETRY values.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions import array, expr
    >>> df = spark.createDataFrame([(['POINT(1 2)','POINT(3 4)'],)], ['wkt_array'])
    >>> df.select(dbf.st_astext(dbf.st_makeline(expr("transform(wkt_array, wkt -> st_geomfromtext(wkt))"))).alias('result')).collect()  # noqa
    [Row(result='LINESTRING(1 2,3 4)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_makeline(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_makepolygon(
    col1: "ColumnOrName",
    col2: Optional["ColumnOrName"] = None
) -> Column:
    """Constructs a polygon from the input outer boundary and optional array of inner boundaries,
    represented as closed linestrings.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value representing the outer boundary of the polygon.
    col2 : :class:`~pyspark.sql.Column`, optional
        An optional array of GEOMETRY values representing the inner boundaries of the polygon.
        Default is an empty array.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(0 0,10 0,10 10,0 10,0 0)',)], ['wkt'])
    >>> df.select(dbf.st_astext(dbf.st_makepolygon(dbf.st_geomfromtext('wkt'))).alias('result')).collect()  # noqa
    [Row(result='POLYGON((0 0,10 0,10 10,0 10,0 0))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col2 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_makepolygon(
            to_java_column(col1)
        )
    else:
        jc = sc._jvm.com.databricks.sql.functions.st_makepolygon(
            to_java_column(col1), to_java_column(col2)
        )
    return Column(jc)


@try_remote_edge_functions
def st_multi(col: "ColumnOrName") -> Column:
    """Returns the input GEOGRAPHY or GEOMETRY value as an equivalent multi geospatial value,
    keeping the original SRID.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    Multi geospatial values and geometry collections are returned as is, with the same SRID.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT M (1 2 4)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_multi(dbf.st_geomfromtext('wkt', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;MULTIPOINT M ((1 2 4))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT ZM ((1 2 3 4))',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_multi(dbf.st_geogfromtext('wkt'))).alias('result')).collect()
    [Row(result='SRID=4326;MULTIPOINT ZM ((1 2 3 4))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_multi(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_ndims(col: "ColumnOrName") -> Column:
    """Returns the coordinate dimension of the input GEOGRAPHY or GEOMETRY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT ZM (10 34 48 -24)',)], ['wkt'])
    >>> df.select(dbf.st_ndims(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=4)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_ndims(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_npoints(col: "ColumnOrName") -> Column:
    """Returns the number of non-empty points in the input GEOGRAPHY or GEOMETRY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(10 34,44 57,EMPTY)',)], ['wkt'])
    >>> df.select(dbf.st_npoints(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=2)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_npoints(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_numgeometries(col: "ColumnOrName") -> Column:
    """Returns the number of geometries in the input geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT((1 2),EMPTY,EMPTY,(3 4))',)], ['wkt'])
    >>> df.select(dbf.st_numgeometries(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=4)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_numgeometries(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_perimeter(col: "ColumnOrName") -> Column:
    """Returns the perimeter of the input geography or geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    If the input is a geometry, Cartesian length is returned (in the unit of the input coordinates).
    If the input is a geography, length on the WGS84 spheroid is returned (expressed in meters).
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from pyspark.sql.functions.builtin import round
    >>> df = spark.createDataFrame([('POLYGON((0 0,50 0,50 50,0 50,0 0),(20 20,25 30,30 20,20 20))',)], ['wkt'])  # noqa
    >>> df.select(round(dbf.st_perimeter(dbf.st_geomfromtext('wkt')), 2).alias('result')).collect()
    [Row(result=232.36)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_perimeter(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_point(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Optional[Union["ColumnOrName", int]] = None
) -> Column:
    """Returns a 2D point GEOMETRY with the given x and y coordinates and SRID value. If no SRID
    value is provided, or if the provided SRID value is negative, the SRID value of the point
    geometry will be set to 0.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or float
        The X coordinate of the point geometry.
    col2 : :class:`~pyspark.sql.Column` or float
        The Y coordinate of the point geometry.
    col3 : :class:`~pyspark.sql.Column` or int, optional
        The SRID value of the point geometry.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(1.0, 2.0, 4326,)], ['x', 'y', 'srid'])
    >>> df.select(dbf.st_asewkt(dbf.st_point('x', 'y', 'srid')).alias('result')).collect()
    [Row(result='SRID=4326;POINT(1 2)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(1.0, 2.0,)], ['x', 'y'])
    >>> df.select(dbf.st_asewkt(dbf.st_point('x', 'y', 0)).alias('result')).collect()
    [Row(result='POINT(1 2)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(1.0, 2.0, 0,)], ['x', 'y', 'srid'])
    >>> df.select(dbf.st_asewkt(dbf.st_point('x', 'y', 'srid')).alias('result')).collect()
    [Row(result='POINT(1 2)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(1.0, 2.0,)], ['x', 'y'])
    >>> df.select(dbf.st_asewkt(dbf.st_point('x', 'y')).alias('result')).collect()
    [Row(result='POINT(1 2)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    if col3 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_point(
            to_java_column(col1), to_java_column(col2)
        )
    else:
        col3 = lit(col3) if isinstance(col3, int) else col3
        jc = sc._jvm.com.databricks.sql.functions.st_point(
            to_java_column(col1), to_java_column(col2), to_java_column(col3)
        )
    return Column(jc)


@try_remote_edge_functions
def st_pointfromgeohash(col: "ColumnOrName") -> Column:
    """Returns the center of the geohash grid box corresponding to the input geohash value as a 2D
    point geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value representing a geohash value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('9q8yyh',)], ['geohash'])
    >>> df.select(dbf.st_astext(dbf.st_pointfromgeohash('geohash')).alias('result')).collect()
    [Row(result='POINT(-122.4261474609375 37.77374267578125)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_pointfromgeohash(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_rotate(col1: "ColumnOrName", col2: Union["ColumnOrName", float]) -> Column:
    """Rotates the input geometry around the Z axis by the given rotation angle (in radians).

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or float
        A DOUBLE value representing the rotation angle (in radians).

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> from math import pi
    >>> df = spark.createDataFrame([('POINT ZM (3 -2 40 27)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_rotate(dbf.st_geomfromtext('wkt', 4326), pi / 2)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POINT ZM (2 3 40 27)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, float) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_rotate(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_setpoint(
    col1: "ColumnOrName",
    col2: Union["ColumnOrName", int],
    col3: "ColumnOrName"
) -> Column:
    """Sets the n-th point in the input linestring GEOGRAPHY or GEOMETRY.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value representing a linestring.
    col2 : :class:`~pyspark.sql.Column` or int
        A 1-based position in the linestring where the new point should be added.
    col3 : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value representing a point.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)','POINT(7 8)',)], ['wkt1', 'wkt2'])
    >>> df.select(dbf.st_astext(dbf.st_setpoint(dbf.st_geomfromtext('wkt1'), 1, dbf.st_geomfromtext('wkt2'))).alias('result')).collect()  # noqa
    [Row(result='LINESTRING(7 8,3 4)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING ZM (1 2 3 4,5 6 7 8)','POINT M (0 9 99)',)], ['wkt1', 'wkt2'])
    >>> df.select(dbf.st_asewkt(dbf.st_setpoint(dbf.st_geogfromtext('wkt1'), -1, dbf.st_geogfromtext('wkt2'))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;LINESTRING ZM (1 2 3 4,0 9 0 99)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_setpoint(
        to_java_column(col1), to_java_column(col2), to_java_column(col3)
    )
    return Column(jc)


@try_remote_edge_functions
def st_removepoint(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Removes the n-th point from the input linestring GEOGRAPHY or GEOMETRY.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or int
        A 1-based position in the linestring indicating the point that should be removed.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4,5 6)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_removepoint(dbf.st_geogfromtext('wkt'), 2)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;LINESTRING(1 2,5 6)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_removepoint(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_scale(
    col1: "ColumnOrName",
    col2: Union["ColumnOrName", float],
    col3: Union["ColumnOrName", float],
    col4: Optional[Union["ColumnOrName", float]] = None
) -> Column:
    """Scales the input geometry in the X, Y, and Z (optional) directions using the given factors.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or float
        A DOUBLE value representing the X scaling factor.
    col3 : :class:`~pyspark.sql.Column` or float
        A DOUBLE value representing the Y scaling factor.
    col4 : :class:`~pyspark.sql.Column` or float, optional
        A DOUBLE value representing the Z scaling factor (optional). Default is 1.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT ZM (1 2 3 -4,5 6 7 -8,EMPTY)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_scale(dbf.st_geomfromtext('wkt', 4326), 10.0, 20.0)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;MULTIPOINT ZM ((10 40 3 -4),(50 120 7 -8),EMPTY)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT ZM (1 2 3 -4,5 6 7 -8,EMPTY)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_scale(dbf.st_geomfromtext('wkt', 4326), 10.0, 20.0, 3.0)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;MULTIPOINT ZM ((10 40 9 -4),(50 120 21 -8),EMPTY)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, float) else col2
    col3 = lit(col3) if isinstance(col3, float) else col3
    if col4 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_scale(
            to_java_column(col1), to_java_column(col2), to_java_column(col3)
        )
    else:
        col4 = lit(col4) if isinstance(col4, float) else col4
        jc = sc._jvm.com.databricks.sql.functions.st_scale(
            to_java_column(col1), to_java_column(col2), to_java_column(col3), to_java_column(col4)
        )
    return Column(jc)


@try_remote_edge_functions
def st_pointn(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns the 1-based n-th point of the input linestring, or NULL if it doesn't exist.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value representing a linestring.
    col2 : :class:`~pyspark.sql.Column` or int
        A 1-based position in the linestring indicating the point that should be returned.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4,5 6)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_pointn(dbf.st_geogfromtext('wkt'), 3)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POINT(5 6)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING ZM (1 2 3 4,5 6 7 8)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_pointn(dbf.st_geomfromtext('wkt', 4326), -2)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POINT ZM (1 2 3 4)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_pointn(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_reverse(col: "ColumnOrName") -> Column:
    """Reverses the order of vertices in the input GEOGRAPHY or GEOMETRY value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4,5 6)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_reverse(dbf.st_geogfromtext('wkt'))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;LINESTRING(5 6,3 4,1 2)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_reverse(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_setsrid(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Returns a new GEOMETRY value whose SRID is the specified SRID value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or int
        The new SRID value of the geometry.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(5 6,7 -8)',)], ['wkt'])
    >>> df.select(dbf.st_srid(dbf.st_setsrid(dbf.st_geomfromtext('wkt'), 4326)).alias('result')).collect()  # noqa
    [Row(result=4326)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(5 6,7 -8)', 3857,)], ['wkt', 'srid'])
    >>> df.select(dbf.st_srid(dbf.st_setsrid(dbf.st_geomfromtext('wkt', 'srid'), 4326)).alias('result')).collect()  # noqa
    [Row(result=4326)]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_setsrid(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_simplify(col1: "ColumnOrName", col2: Union["ColumnOrName", float]) -> Column:
    """Simplifies the input geometry using the Douglas-Peucker algorithm.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or float
        A DOUBLE value that is the distance value used for the simplification.
        The distance units are those of the CRS of the input geometry.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(0 0,5.1 0,10 0,10 3,10 8,16 9)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_simplify(dbf.st_geomfromtext('wkt', 4326), 0.2)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;LINESTRING(0 0,10 0,10 8,16 9)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, float) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_simplify(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_srid(col: "ColumnOrName") -> Column:
    """Returns the SRID of the input geospatial value.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(10 34)',)], ['wkt'])
    >>> df.select(dbf.st_srid(dbf.st_geogfromtext('wkt')).alias('result')).collect()
    [Row(result=4326)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4)', '3857',)], ['wkt', 'srid'])
    >>> df.select(dbf.st_srid(dbf.st_geomfromtext('wkt', 'srid')).alias('result')).collect()
    [Row(result=3857)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_srid(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_startpoint(col: "ColumnOrName") -> Column:
    """Returns the first point of the input linestring, or NULL if it doesn't exist.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOGRAPHY or GEOMETRY value representing a linestring.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(1 2,3 4,5 6)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_startpoint(dbf.st_geogfromtext('wkt'))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POINT(1 2)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING ZM (1 2 3 4,5 6 7 8)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_startpoint(dbf.st_geomfromtext('wkt', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;POINT ZM (1 2 3 4)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_startpoint(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_touches(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns `true` if the two geometries touch each other. Geometry collections are not supported.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(5 0,5 10)','MULTILINESTRING((0 0,10 10),(0 10,10 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_touches(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect()
    [Row(result=False)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING(5 5,5 0,10 0)','MULTILINESTRING((0 0,10 10),(0 10,10 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_touches(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect()
    [Row(result=True)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_touches(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_transform(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> Column:
    """Transforms the X and Y coordinates of the input geometry to the coordinate reference system
    (CRS) described by the provided SRID value. Z and M coordinates are not transformed.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or int
        The SRID value of the new coordinate reference system (CRS) to which the input geometry
        should be transformed.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.
    """
    # We separate the example as they need the PROJ_DATA environment variable properly set up to be
    # run correctly.
    """
    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT Z (4 5 14,-3 8 27,EMPTY)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_transform(dbf.st_geomfromtext('wkt', 4326), 3857)).alias('result')).collect()  # noqa
    [Row(result='SRID=3857;MULTIPOINT Z ((445277.96317309426 557305.2572745768 14),(-333958.4723798207 893463.751012646 27),EMPTY)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, int) else col2
    jc = sc._jvm.com.databricks.sql.functions.st_transform(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_translate(
    col1: "ColumnOrName",
    col2: Union["ColumnOrName", float],
    col3: Union["ColumnOrName", float],
    col4: Optional[Union["ColumnOrName", float]] = None
) -> Column:
    """Translates the input geometry in the X, Y, and Z (optional) directions using the provided
    offsets.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or float
        A DOUBLE value representing the offset in the X direction.
    col3 : :class:`~pyspark.sql.Column` or float
        A DOUBLE value representing the offset in the Y direction.
    col4 : :class:`~pyspark.sql.Column` or float, optional
        A DOUBLE value representing the offset in the Z direction (optional). Default is 0.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT ZM (1 2 3 -4,5 6 7 -8,EMPTY)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_translate(dbf.st_geomfromtext('wkt', 4326), 10.0, 20.0)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;MULTIPOINT ZM ((11 22 3 -4),(15 26 7 -8),EMPTY)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT ZM (1 2 3 -4,5 6 7 -8,EMPTY)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.st_translate(dbf.st_geomfromtext('wkt', 4326), 10.0, 20.0, 30.0)).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;MULTIPOINT ZM ((11 22 33 -4),(15 26 37 -8),EMPTY)')]
    """
    from pyspark.sql.functions import lit
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    col2 = lit(col2) if isinstance(col2, float) else col2
    col3 = lit(col3) if isinstance(col3, float) else col3
    if col4 is None:
        jc = sc._jvm.com.databricks.sql.functions.st_translate(
            to_java_column(col1), to_java_column(col2), to_java_column(col3)
        )
    else:
        col4 = lit(col4) if isinstance(col4, float) else col4
        jc = sc._jvm.com.databricks.sql.functions.st_translate(
            to_java_column(col1), to_java_column(col2), to_java_column(col3), to_java_column(col4)
        )
    return Column(jc)


@try_remote_edge_functions
def st_union(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns the point-set union of the two input geometries as a 2D geometry.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(EMPTY,4 3,5 6,-1 8)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_union(dbf.st_geomfromtext('wkt1', 4326), dbf.st_geomfromtext('wkt2', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;GEOMETRYCOLLECTION(POINT(-1 8),POINT(5 6),POLYGON((0 0,0 10,10 0,0 0)))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_union(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_union_agg(col: "ColumnOrName") -> Column:
    """Returns the point-wise union of all the geometries in the column, or NULL if the column has
    zero rows, or contains only NULL values.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('MULTIPOINT(EMPTY,4 3,5 6,-1 8)',), ('POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.st_union_agg(dbf.st_geomfromtext('wkt', 4326))).alias('result')).collect()  # noqa
    [Row(result='SRID=4326;GEOMETRYCOLLECTION(MULTIPOINT((-1 8),(5 6)),POLYGON((0 0,10 0,0 10,0 0)))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_union_agg(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_within(col1: "ColumnOrName", col2: "ColumnOrName") -> Column:
    """Returns `true` if the first geometry is within the second geometry. Geometry collections are
    not supported.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col1 : :class:`~pyspark.sql.Column` or str
        The first GEOMETRY value.
    col2 : :class:`~pyspark.sql.Column` or str
        The second GEOMETRY value.

    Notes
    -----
    The two geometries are expected to have the same SRID value, otherwise an error is returned.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(1 1)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_within(dbf.st_geomfromtext('wkt1'), dbf.st_geomfromtext('wkt2')).alias('result')).collect()
    [Row(result=True)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(5 6)','POLYGON((0 0,10 0,0 10,0 0))',)], ['wkt1', 'wkt2'])  # noqa
    >>> df.select(dbf.st_within(dbf.st_geomfromtext('wkt1', 4326), dbf.st_geomfromtext('wkt2', 4326)).alias('result')).collect()
    [Row(result=False)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_within(
        to_java_column(col1), to_java_column(col2)
    )
    return Column(jc)


@try_remote_edge_functions
def st_x(col: "ColumnOrName") -> Column:
    """Returns the X coordinate of the input point geometry, or NULL if the input point geometry is
    empty.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(1 2)',)], ['wkt'])
    >>> df.select(dbf.st_x(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=1.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT ZM (1 2 3 4)',)], ['wkt'])
    >>> df.select(dbf.st_x(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=1.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_x(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_xmax(col: "ColumnOrName") -> Column:
    """Returns the maximum X coordinate of the input geometry, or NULL if the input geometry is
    empty.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING Z (1 2 3,4 5 6,7 8 9)',)], ['wkt'])
    >>> df.select(dbf.st_xmax(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=7.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON Z ((2 0 1,1 2 0,-1 -1 2,0 -1 1, 2 0 1))',)], ['wkt'])
    >>> df.select(dbf.st_xmax(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=2.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_xmax(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_xmin(col: "ColumnOrName") -> Column:
    """Returns the minimum X coordinate of the input geometry, or NULL if the input geometry is
    empty.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING Z (1 2 3,4 5 6,7 8 9)',)], ['wkt'])
    >>> df.select(dbf.st_xmin(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=1.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON Z ((2 0 1,1 2 0,-1 -1 2,0 -1 1, 2 0 1))',)], ['wkt'])
    >>> df.select(dbf.st_xmin(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=-1.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_xmin(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_y(col: "ColumnOrName") -> Column:
    """Returns the Y coordinate of the input point geometry, or NULL if the input point geometry is
    empty.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT(1 2)',)], ['wkt'])
    >>> df.select(dbf.st_y(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=2.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT ZM (1 2 3 4)',)], ['wkt'])
    >>> df.select(dbf.st_y(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=2.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_y(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_ymax(col: "ColumnOrName") -> Column:
    """Returns the maximum Y coordinate of the input geometry, or NULL if the input geometry is
    empty.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING Z (1 2 3,4 5 6,7 8 9)',)], ['wkt'])
    >>> df.select(dbf.st_ymax(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=8.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON Z ((2 0 1,1 2 0,-1 -1 2,0 -1 1, 2 0 1))',)], ['wkt'])
    >>> df.select(dbf.st_ymax(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=2.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_ymax(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_ymin(col: "ColumnOrName") -> Column:
    """Returns the minimum Y coordinate of the input geometry, or NULL if the input geometry is
    empty.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING Z (1 2 3,4 5 6,7 8 9)',)], ['wkt'])
    >>> df.select(dbf.st_ymin(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=2.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON Z ((2 0 1,1 2 0,-1 -1 2,0 -1 1, 2 0 1))',)], ['wkt'])
    >>> df.select(dbf.st_ymin(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=-1.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_ymin(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_z(col: "ColumnOrName") -> Column:
    """Returns the Z coordinate of the input point geometry, or NULL if the input point geometry is
    empty or if it does not have a Z coordinate.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (1 2 3)',)], ['wkt'])
    >>> df.select(dbf.st_z(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=3.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT ZM (1 2 3 4)',)], ['wkt'])
    >>> df.select(dbf.st_z(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=3.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_z(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_zmax(col: "ColumnOrName") -> Column:
    """Returns the maximum Z coordinate of the input geometry, or NULL if the input geometry is
    empty or does not contain Z coordinates.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING Z (1 2 3,4 5 6,7 8 9)',)], ['wkt'])
    >>> df.select(dbf.st_zmax(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=9.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON Z ((2 0 1,1 2 0,-1 -1 2,0 -1 1, 2 0 1))',)], ['wkt'])
    >>> df.select(dbf.st_zmax(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=2.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_zmax(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def st_zmin(col: "ColumnOrName") -> Column:
    """Returns the minimum Z coordinate of the input geometry, or NULL if the input geometry is
    empty or does not contain Z coordinates.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A GEOMETRY value.

    Notes
    -----
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('LINESTRING Z (1 2 3,4 5 6,7 8 9)',)], ['wkt'])
    >>> df.select(dbf.st_zmin(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=3.0)]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POLYGON Z ((2 0 1,1 2 0,-1 -1 2,0 -1 1, 2 0 1))',)], ['wkt'])
    >>> df.select(dbf.st_zmin(dbf.st_geomfromtext('wkt')).alias('result')).collect()
    [Row(result=0.0)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.st_zmin(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def to_geography(col: "ColumnOrName") -> Column:
    """Parses the input BINARY or STRING value and returns the corresponding GEOGRAPHY value.
    An error is thrown for invalid input.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value in WKT or GeoJSON format, or a BINARY value in WKB format
        representing a GEOGRAPHY value.

    Notes
    -----
    The SRID value of the returned GEOGRAPHY value is 4326. This is an EDGE feature that is only
    supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (3 4 5)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.to_geography('wkt')).alias('result')).collect()
    [Row(result='SRID=4326;POINT Z (3 4 5)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('{"type":"MultiPoint","coordinates":[[3,4,5]]}',)], ['geojson'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.to_geography('geojson')).alias('result')).collect()
    [Row(result='SRID=4326;MULTIPOINT Z ((3 4 5))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('01ef0300000100000001e9030000000000000000084000000000000010400000000000001440'),)], ['wkb'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.to_geography('wkb')).alias('result')).collect()
    [Row(result='SRID=4326;GEOMETRYCOLLECTION Z (POINT Z (3 4 5))')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.to_geography(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def to_geometry(col: "ColumnOrName") -> Column:
    """Parses the input BINARY or STRING value and returns the corresponding GEOMETRY value.
    An error is thrown for invalid input.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value in WKT or GeoJSON format,
        or a BINARY value in WKB or EWKB format representing a GEOMETRY value.

    Notes
    -----
    The SRID value can be specified in EWKB format, but is 4326 for GeoJSON, and 0 for WKT or WKB.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (3 4 5)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.to_geometry('wkt')).alias('result')).collect()
    [Row(result='POINT Z (3 4 5)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('{"type":"MultiPoint","coordinates":[[3,4,5]]}',)], ['geojson'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.to_geometry('geojson')).alias('result')).collect()
    [Row(result='SRID=4326;MULTIPOINT Z ((3 4 5))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('01ef0300000100000001e9030000000000000000084000000000000010400000000000001440'),)], ['wkb'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.to_geometry('wkb')).alias('result')).collect()
    [Row(result='GEOMETRYCOLLECTION Z (POINT Z (3 4 5))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('01020000a0110f000002000000000000000000084000000000000010400000000000001440000000000000084000000000000010400000000000001440'),)], ['ewkb'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.to_geometry('ewkb')).alias('result')).collect()
    [Row(result='SRID=3857;LINESTRING Z (3 4 5,3 4 5)')]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.to_geometry(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def try_to_geography(col: "ColumnOrName") -> Column:
    """Parses the input BINARY or STRING value and returns the corresponding GEOGRAPHY value.
    NULL is returned if the input is invalid.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value in WKT or GeoJSON format, or a BINARY value in WKB format
        representing a GEOGRAPHY value.

    Notes
    -----
    The SRID value of the returned GEOGRAPHY value is 4326. This is an EDGE feature that is only
    supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (3 4 5)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.try_to_geography('wkt')).alias('result')).collect()
    [Row(result='SRID=4326;POINT Z (3 4 5)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('{"type":"MultiPoint","coordinates":[[3,4,5]]}',)], ['geojson'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.try_to_geography('geojson')).alias('result')).collect()
    [Row(result='SRID=4326;MULTIPOINT Z ((3 4 5))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('01ef0300000100000001e9030000000000000000084000000000000010400000000000001440'),)], ['wkb'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.try_to_geography('wkb')).alias('result')).collect()
    [Row(result='SRID=4326;GEOMETRYCOLLECTION Z (POINT Z (3 4 5))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('invalid wkt',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.try_to_geography('wkt')).alias('result')).collect()
    [Row(result=None)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.try_to_geography(to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def try_to_geometry(col: "ColumnOrName") -> Column:
    """Parses the input BINARY or STRING value and returns the corresponding GEOMETRY value.
    NULL is returned if the input is invalid.

    .. versionadded:: 3.5.0

    Parameters
    ----------
    col : :class:`~pyspark.sql.Column` or str
        A STRING value in WKT or GeoJSON format,
        or a BINARY value in WKB or EWKB format representing a GEOMETRY value.

    Notes
    -----
    The SRID value can be specified in EWKB format, but is 4326 for GeoJSON, and 0 for WKT or WKB.
    This is an EDGE feature that is only supported in DBR.

    Examples
    --------
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('POINT Z (3 4 5)',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.try_to_geometry('wkt')).alias('result')).collect()
    [Row(result='POINT Z (3 4 5)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('{"type":"MultiPoint","coordinates":[[3,4,5]]}',)], ['geojson'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.try_to_geometry('geojson')).alias('result')).collect()
    [Row(result='SRID=4326;MULTIPOINT Z ((3 4 5))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('01ef0300000100000001e9030000000000000000084000000000000010400000000000001440'),)], ['wkb'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.try_to_geometry('wkb')).alias('result')).collect()
    [Row(result='GEOMETRYCOLLECTION Z (POINT Z (3 4 5))')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([(bytes.fromhex('01020000a0110f000002000000000000000000084000000000000010400000000000001440000000000000084000000000000010400000000000001440'),)], ['ewkb'])  # noqa
    >>> df.select(dbf.st_asewkt(dbf.try_to_geometry('ewkb')).alias('result')).collect()
    [Row(result='SRID=3857;LINESTRING Z (3 4 5,3 4 5)')]
    >>> from pyspark.databricks.sql import functions as dbf
    >>> df = spark.createDataFrame([('invalid wkt',)], ['wkt'])
    >>> df.select(dbf.st_asewkt(dbf.try_to_geometry('wkt')).alias('result')).collect()
    [Row(result=None)]
    """
    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None
    jc = sc._jvm.com.databricks.sql.functions.try_to_geometry(to_java_column(col))
    return Column(jc)


def _test() -> None:
    import doctest
    from pyspark.sql import SparkSession
    import pyspark.databricks.sql.st_functions

    globs = pyspark.databricks.sql.st_functions.__dict__.copy()
    spark = (
        SparkSession.builder.master("local[4]")
        .appName("databricks.sql.st_functions tests")
        .getOrCreate()
    )
    sc = spark.sparkContext
    globs["sc"] = sc
    globs["spark"] = spark
    (failure_count, test_count) = doctest.testmod(
        pyspark.databricks.sql.st_functions,
        globs=globs,
        optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE,
    )
    spark.stop()
    if failure_count:
        sys.exit(-1)


if __name__ == "__main__":
    _test()
