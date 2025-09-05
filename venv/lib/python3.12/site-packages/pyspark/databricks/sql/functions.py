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
import sys
from typing import TYPE_CHECKING, Union

from pyspark import since, SparkContext
from pyspark.sql.column import Column
from pyspark.sql.utils import try_remote_edge_functions

from pyspark.databricks.sql.h3_functions import (  # noqa: F401
    h3_boundaryasgeojson,  # noqa: F401
    h3_boundaryaswkb,  # noqa: F401
    h3_boundaryaswkt,  # noqa: F401
    h3_centerasgeojson,  # noqa: F401
    h3_centeraswkb,  # noqa: F401
    h3_centeraswkt,  # noqa: F401
    h3_compact,  # noqa: F401
    h3_coverash3,  # noqa: F401
    h3_coverash3string,  # noqa: F401
    h3_distance,  # noqa: F401
    h3_h3tostring,  # noqa: F401
    h3_hexring,  # noqa: F401
    h3_ischildof,  # noqa: F401
    h3_ispentagon,  # noqa: F401
    h3_isvalid,  # noqa: F401
    h3_kring,  # noqa: F401
    h3_kringdistances,  # noqa: F401
    h3_longlatash3,  # noqa: F401
    h3_longlatash3string,  # noqa: F401
    h3_maxchild,  # noqa: F401
    h3_minchild,  # noqa: F401
    h3_pointash3,  # noqa: F401
    h3_pointash3string,  # noqa: F401
    h3_polyfillash3,  # noqa: F401
    h3_polyfillash3string,  # noqa: F401
    h3_resolution,  # noqa: F401
    h3_stringtoh3,  # noqa: F401
    h3_tessellateaswkb,  # noqa: F401
    h3_tochildren,  # noqa: F401
    h3_toparent,  # noqa: F401
    h3_try_coverash3,  # noqa: F401
    h3_try_coverash3string,  # noqa: F401
    h3_try_distance,  # noqa: F401
    h3_try_polyfillash3,  # noqa: F401
    h3_try_polyfillash3string,  # noqa: F401
    h3_try_tessellateaswkb,  # noqa: F401
    h3_try_validate,  # noqa: F401
    h3_uncompact,  # noqa: F401
    h3_validate,  # noqa: F401
)  # noqa: F401

from pyspark.databricks.sql.st_functions import (  # noqa: F401
    st_addpoint,  # noqa: F401
    st_area,  # noqa: F401
    st_asbinary,  # noqa: F401
    st_asewkb,  # noqa: F401
    st_asewkt,  # noqa: F401
    st_asgeojson,  # noqa: F401
    st_astext,  # noqa: F401
    st_aswkb,  # noqa: F401
    st_aswkt,  # noqa: F401
    st_buffer,  # noqa: F401
    st_centroid,  # noqa: F401
    st_concavehull,  # noqa: F401
    st_contains,  # noqa: F401
    st_convexhull,  # noqa: F401
    st_covers,  # noqa: F401
    st_difference,  # noqa: F401
    st_dimension,  # noqa: F401
    st_disjoint,  # noqa: F401
    st_distance,  # noqa: F401
    st_distancesphere,  # noqa: F401
    st_distancespheroid,  # noqa: F401
    st_dwithin,  # noqa: F401
    st_endpoint,  # noqa: F401
    st_envelope,  # noqa: F401
    st_envelope_agg,  # noqa: F401
    st_equals,  # noqa: F401
    st_flipcoordinates,  # noqa: F401
    st_geogfromgeojson,  # noqa: F401
    st_geogfromtext,  # noqa: F401
    st_geogfromwkb,  # noqa: F401
    st_geogfromwkt,  # noqa: F401
    st_geohash,  # noqa: F401
    st_geometryn,  # noqa: F401
    st_geometrytype,  # noqa: F401
    st_geomfromewkb,  # noqa: F401
    st_geomfromgeohash,  # noqa: F401
    st_geomfromgeojson,  # noqa: F401
    st_geomfromtext,  # noqa: F401
    st_geomfromwkb,  # noqa: F401
    st_geomfromwkt,  # noqa: F401
    st_intersection,  # noqa: F401
    st_intersects,  # noqa: F401
    st_isempty,  # noqa: F401
    st_isvalid,  # noqa: F401
    st_length,  # noqa: F401
    st_m,  # noqa: F401
    st_makeline,  # noqa: F401
    st_makepolygon,  # noqa: F401
    st_multi,  # noqa: F401
    st_ndims,  # noqa: F401
    st_npoints,  # noqa: F401
    st_numgeometries,  # noqa: F401
    st_perimeter,  # noqa: F401
    st_point,  # noqa: F401
    st_pointfromgeohash,  # noqa: F401
    st_pointn,  # noqa: F401
    st_reverse,  # noqa: F401
    st_rotate,  # noqa: F401
    st_removepoint,  # noqa: F401
    st_scale,  # noqa: F401
    st_setpoint,  # noqa: F401
    st_setsrid,  # noqa: F401
    st_simplify,  # noqa: F401
    st_srid,  # noqa: F401
    st_startpoint,  # noqa: F401
    st_touches,  # noqa: F401
    st_transform,  # noqa: F401
    st_translate,  # noqa: F401
    st_union,  # noqa: F401
    st_union_agg,  # noqa: F401
    st_within,  # noqa: F401
    st_x,  # noqa: F401
    st_xmax,  # noqa: F401
    st_xmin,  # noqa: F401
    st_y,  # noqa: F401
    st_ymax,  # noqa: F401
    st_ymin,  # noqa: F401
    st_z,  # noqa: F401
    st_zmax,  # noqa: F401
    st_zmin,  # noqa: F401
    to_geography,  # noqa: F401
    to_geometry,  # noqa: F401
    try_to_geography,  # noqa: F401
    try_to_geometry,  # noqa: F401
)  # noqa: F401

if TYPE_CHECKING:
    from pyspark.sql._typing import ColumnOrName


@since("3.0.1")
def unwrap_udt(col):
    """
    Unwrap UDT data type column into its underlying struct type
    """
    from pyspark.sql.classic.column import _to_java_column

    sc = SparkContext._active_spark_context
    jc = sc._jvm.com.databricks.sql.DatabricksFunctions.unwrap_udt(_to_java_column(col))
    return Column(jc)


@try_remote_edge_functions
def approx_top_k(
    col: "ColumnOrName",
    k: Union[Column, int] = 5,
    maxItemsTracked: Union[Column, int] = 10000,
) -> Column:
    """Returns the top `k` most frequently occurring item values in a string, boolean, date,
    timestamp, or numeric column `col` along with their approximate counts. The error in each count
    may be up to `2.0 * numRows / maxItemsTracked` where `numRows` is the total number of rows.
    `k` (default: 5) and `maxItemsTracked` (default: 10000) are both integer parameters.
    Higher values  of `maxItemsTracked` provide better accuracy at the cost of increased memory
    usage. Columns that have fewer than `maxItemsTracked` distinct items will yield exact item
    counts.  NULL values are included as their own value in the results.

    Results are returned as an array of structs containing `item` values (with their original input
    type) and their occurrence `count` (long type), sorted by count descending.

    .. versionadded:: 3.3.0

    .. versionchanged:: 3.5.0
        Supports Spark Connect.

    Examples
    --------
    >>> from pyspark.sql.functions import col
    >>> item = (col("id") % 3).alias("item")
    >>> df = spark.range(0, 1000, 1, 1).select(item)
    >>> df.select(
    ...    approx_top_k("item", 5).alias("top_k")
    ... ).printSchema()
    root
     |-- top_k: array (nullable = true)
     |    |-- element: struct (containsNull = true)
     |    |    |-- item: long (nullable = true)
     |    |    |-- count: long (nullable = true)
    """
    from pyspark.sql.classic.column import Column, _create_column_from_literal, _to_java_column

    sc = SparkContext._active_spark_context
    assert sc is not None and sc._jvm is not None

    k_col = _to_java_column(k) if isinstance(k, Column) else _create_column_from_literal(k)
    max_items_tracked_col = (
        _to_java_column(maxItemsTracked)
        if isinstance(maxItemsTracked, Column)
        else _create_column_from_literal(maxItemsTracked)
    )
    jc = sc._jvm.com.databricks.sql.DatabricksFunctions.approx_top_k(
        _to_java_column(col), k_col, max_items_tracked_col
    )
    return Column(jc)


def _test() -> None:
    import doctest
    from pyspark.sql import SparkSession
    import pyspark.databricks.sql.functions

    globs = pyspark.databricks.sql.functions.__dict__.copy()
    spark = (
        SparkSession.builder.master("local[4]")
        .appName("databricks.sql.functions tests")
        .getOrCreate()
    )
    sc = spark.sparkContext
    globs["sc"] = sc
    globs["spark"] = spark
    (failure_count, test_count) = doctest.testmod(
        pyspark.databricks.sql.functions,
        globs=globs,
        optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE,
    )
    spark.stop()
    if failure_count:
        sys.exit(-1)


if __name__ == "__main__":
    _test()
