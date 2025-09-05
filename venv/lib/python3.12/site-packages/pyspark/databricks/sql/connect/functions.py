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

from pyspark.databricks.sql import functions as pyspark_db_funcs

from pyspark.errors import PySparkTypeError
from pyspark.sql.connect.column import Column
from pyspark.sql.connect.functions.builtin import _invoke_function_over_columns, lit

from pyspark.databricks.sql.connect.h3_functions import (  # noqa: F401
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

from pyspark.databricks.sql.connect.st_functions import (  # noqa: F401
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
    st_pointn,  # noqa: F401
    st_reverse,  # noqa: F401
    st_pointfromgeohash,  # noqa: F401
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
    from pyspark.sql.connect._typing import ColumnOrName


def approx_top_k(
    col: "ColumnOrName",
    k: Union[Column, int] = 5,
    maxItemsTracked: Union[Column, int] = 10000,
) -> Column:
    if isinstance(k, int):
        _k = lit(k)
    elif isinstance(k, Column):
        _k = k
    else:
        raise PySparkTypeError(
            errorClass="NOT_COLUMN_OR_INT",
            messageParameters={
                "arg_name": "k",
                "arg_type": type(k).__name__,
            },
        )

    if isinstance(maxItemsTracked, int):
        _maxItemsTracked = lit(maxItemsTracked)
    elif isinstance(maxItemsTracked, Column):
        _maxItemsTracked = maxItemsTracked
    else:
        raise PySparkTypeError(
            errorClass="NOT_COLUMN_OR_INT",
            messageParameters={
                "arg_name": "maxItemsTracked",
                "arg_type": type(maxItemsTracked).__name__,
            },
        )

    return _invoke_function_over_columns("approx_top_k", col, _k, _maxItemsTracked)


approx_top_k.__doc__ = pyspark_db_funcs.approx_top_k.__doc__


def _test() -> None:
    import sys
    import doctest
    from pyspark.sql import SparkSession as PySparkSession
    import pyspark.databricks.sql.connect.functions

    globs = pyspark.databricks.sql.connect.functions.__dict__.copy()

    globs["spark"] = (
        PySparkSession.builder.appName("databricks.sql.connect.functions tests")
        .remote("local[4]")
        .getOrCreate()
    )
    # Setup Scope for UC Testing.
    from pyspark.testing.connectutils import ReusedConnectTestCase

    ReusedConnectTestCase.update_client_for_uc(globs["spark"])

    (failure_count, test_count) = doctest.testmod(
        pyspark.databricks.sql.connect.functions,
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
