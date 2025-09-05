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
from typing import TYPE_CHECKING, Optional, Union

from pyspark.databricks.sql import st_functions as pyspark_db_st_funcs

from pyspark.sql.connect.functions.builtin import _invoke_function_over_columns, lit


if TYPE_CHECKING:
    from pyspark.sql.connect._typing import ColumnOrName
    from pyspark.sql.connect.column import Column


def st_addpoint(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Union["ColumnOrName", int] = -1
) -> "Column":
    _col3 = lit(col3) if isinstance(col3, int) else col3
    return _invoke_function_over_columns("st_addpoint", col1, col2, _col3)


st_addpoint.__doc__ = pyspark_db_st_funcs.st_addpoint.__doc__


def st_area(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_area", col)


st_area.__doc__ = pyspark_db_st_funcs.st_area.__doc__


def st_asbinary(
    col1: "ColumnOrName",
    col2: Optional["ColumnOrName"] = None
) -> "Column":
    if col2 is None:
        return _invoke_function_over_columns("st_asbinary", col1)
    else:
        _col2 = lit(col2) if isinstance(col2, str) else col2
        return _invoke_function_over_columns("st_asbinary", col1, _col2)


st_asbinary.__doc__ = pyspark_db_st_funcs.st_asbinary.__doc__


def st_asewkb(
    col1: "ColumnOrName",
    col2: Optional["ColumnOrName"] = None
) -> "Column":
    if col2 is None:
        return _invoke_function_over_columns("st_asewkb", col1)
    else:
        _col2 = lit(col2) if isinstance(col2, str) else col2
        return _invoke_function_over_columns("st_asewkb", col1, _col2)


st_asewkb.__doc__ = pyspark_db_st_funcs.st_asewkb.__doc__


def st_asewkt(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_asewkt", col)


st_asewkt.__doc__ = pyspark_db_st_funcs.st_asewkt.__doc__


def st_asgeojson(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_asgeojson", col)


st_asgeojson.__doc__ = pyspark_db_st_funcs.st_asgeojson.__doc__


def st_astext(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_astext", col)


st_astext.__doc__ = pyspark_db_st_funcs.st_astext.__doc__


def st_aswkb(
    col1: "ColumnOrName",
    col2: Optional["ColumnOrName"] = None
) -> "Column":
    if col2 is None:
        return _invoke_function_over_columns("st_aswkb", col1)
    else:
        _col2 = lit(col2) if isinstance(col2, str) else col2
        return _invoke_function_over_columns("st_aswkb", col1, _col2)


st_aswkb.__doc__ = pyspark_db_st_funcs.st_aswkb.__doc__


def st_aswkt(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_aswkt", col)


st_aswkt.__doc__ = pyspark_db_st_funcs.st_aswkt.__doc__


def st_buffer(col1: "ColumnOrName", col2: Union["ColumnOrName", float]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, float) else col2
    return _invoke_function_over_columns("st_buffer", col1, _col2)


st_buffer.__doc__ = pyspark_db_st_funcs.st_buffer.__doc__


def st_centroid(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_centroid", col)


st_centroid.__doc__ = pyspark_db_st_funcs.st_centroid.__doc__


def st_concavehull(
    col1: "ColumnOrName",
    col2: Union["ColumnOrName", float],
    col3: Optional[Union["ColumnOrName", bool]] = None
) -> "Column":
    _col2 = lit(col2) if isinstance(col2, float) else col2
    if col3 is None:
        return _invoke_function_over_columns("st_concavehull", col1, _col2)
    else:
        _col3 = lit(col3) if isinstance(col3, bool) else col3
        return _invoke_function_over_columns("st_concavehull", col1, _col2, _col3)


st_concavehull.__doc__ = pyspark_db_st_funcs.st_concavehull.__doc__


def st_contains(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_contains", col1, col2)


st_contains.__doc__ = pyspark_db_st_funcs.st_contains.__doc__


def st_convexhull(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_convexhull", col)


st_convexhull.__doc__ = pyspark_db_st_funcs.st_convexhull.__doc__


def st_covers(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_covers", col1, col2)


st_covers.__doc__ = pyspark_db_st_funcs.st_covers.__doc__


def st_difference(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_difference", col1, col2)


st_difference.__doc__ = pyspark_db_st_funcs.st_difference.__doc__


def st_dimension(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_dimension", col)


st_dimension.__doc__ = pyspark_db_st_funcs.st_dimension.__doc__


def st_disjoint(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_disjoint", col1, col2)


st_disjoint.__doc__ = pyspark_db_st_funcs.st_disjoint.__doc__


def st_distance(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_distance", col1, col2)


st_distance.__doc__ = pyspark_db_st_funcs.st_distance.__doc__


def st_distancesphere(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_distancesphere", col1, col2)


st_distancesphere.__doc__ = pyspark_db_st_funcs.st_distancesphere.__doc__


def st_distancespheroid(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_distancespheroid", col1, col2)


st_distancespheroid.__doc__ = pyspark_db_st_funcs.st_distancespheroid.__doc__


def st_dwithin(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Union["ColumnOrName", float]
) -> "Column":
    _col3 = lit(col3) if isinstance(col3, float) else col3
    return _invoke_function_over_columns("st_dwithin", col1, col2, _col3)


st_dwithin.__doc__ = pyspark_db_st_funcs.st_dwithin.__doc__


def st_endpoint(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_endpoint", col)


st_endpoint.__doc__ = pyspark_db_st_funcs.st_endpoint.__doc__


def st_envelope(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_envelope", col)


st_envelope.__doc__ = pyspark_db_st_funcs.st_envelope.__doc__


def st_envelope_agg(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_envelope_agg", col)


st_envelope_agg.__doc__ = pyspark_db_st_funcs.st_envelope_agg.__doc__


def st_equals(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_equals", col1, col2)


st_equals.__doc__ = pyspark_db_st_funcs.st_equals.__doc__


def st_flipcoordinates(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_flipcoordinates", col)


st_flipcoordinates.__doc__ = pyspark_db_st_funcs.st_flipcoordinates.__doc__


def st_geogfromgeojson(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_geogfromgeojson", col)


st_geogfromgeojson.__doc__ = pyspark_db_st_funcs.st_geogfromgeojson.__doc__


def st_geogfromtext(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_geogfromtext", col)


st_geogfromtext.__doc__ = pyspark_db_st_funcs.st_geogfromtext.__doc__


def st_geogfromwkb(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_geogfromwkb", col)


st_geogfromwkb.__doc__ = pyspark_db_st_funcs.st_geogfromwkb.__doc__


def st_geogfromwkt(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_geogfromwkt", col)


st_geogfromwkt.__doc__ = pyspark_db_st_funcs.st_geogfromwkt.__doc__


def st_geohash(
    col1: "ColumnOrName",
    col2: Optional[Union["ColumnOrName", int]] = None
) -> "Column":
    if col2 is None:
        return _invoke_function_over_columns("st_geohash", col1)
    else:
        _col2 = lit(col2) if isinstance(col2, int) else col2
        return _invoke_function_over_columns("st_geohash", col1, _col2)


st_geohash.__doc__ = pyspark_db_st_funcs.st_geohash.__doc__


def st_geometryn(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("st_geometryn", col1, _col2)


st_geometryn.__doc__ = pyspark_db_st_funcs.st_geometryn.__doc__


def st_geometrytype(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_geometrytype", col)


st_geometrytype.__doc__ = pyspark_db_st_funcs.st_geometrytype.__doc__


def st_geomfromewkb(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_geomfromewkb", col)


st_geomfromewkb.__doc__ = pyspark_db_st_funcs.st_geomfromewkb.__doc__


def st_geomfromgeohash(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_geomfromgeohash", col)


st_geomfromgeohash.__doc__ = pyspark_db_st_funcs.st_geomfromgeohash.__doc__


def st_geomfromgeojson(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_geomfromgeojson", col)


st_geomfromgeojson.__doc__ = pyspark_db_st_funcs.st_geomfromgeojson.__doc__


def st_geomfromtext(
    col1: "ColumnOrName",
    col2: Optional[Union["ColumnOrName", int]] = None
) -> "Column":
    if col2 is None:
        return _invoke_function_over_columns("st_geomfromtext", col1)
    else:
        _col2 = lit(col2) if isinstance(col2, int) else col2
        return _invoke_function_over_columns("st_geomfromtext", col1, _col2)


st_geomfromtext.__doc__ = pyspark_db_st_funcs.st_geomfromtext.__doc__


def st_geomfromwkb(
    col1: "ColumnOrName",
    col2: Optional[Union["ColumnOrName", int]] = None
) -> "Column":
    if col2 is None:
        return _invoke_function_over_columns("st_geomfromwkb", col1)
    else:
        _col2 = lit(col2) if isinstance(col2, int) else col2
        return _invoke_function_over_columns("st_geomfromwkb", col1, _col2)


st_geomfromwkb.__doc__ = pyspark_db_st_funcs.st_geomfromwkb.__doc__


def st_geomfromwkt(
    col1: "ColumnOrName",
    col2: Optional[Union["ColumnOrName", int]] = None
) -> "Column":
    if col2 is None:
        return _invoke_function_over_columns("st_geomfromwkt", col1)
    else:
        _col2 = lit(col2) if isinstance(col2, int) else col2
        return _invoke_function_over_columns("st_geomfromwkt", col1, _col2)


st_geomfromwkt.__doc__ = pyspark_db_st_funcs.st_geomfromwkt.__doc__


def st_intersection(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_intersection", col1, col2)


st_intersection.__doc__ = pyspark_db_st_funcs.st_intersection.__doc__


def st_intersects(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_intersects", col1, col2)


st_intersects.__doc__ = pyspark_db_st_funcs.st_intersects.__doc__


def st_isempty(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_isempty", col)


st_isempty.__doc__ = pyspark_db_st_funcs.st_isempty.__doc__


def st_isvalid(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_isvalid", col)


st_isvalid.__doc__ = pyspark_db_st_funcs.st_isvalid.__doc__


def st_length(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_length", col)


st_length.__doc__ = pyspark_db_st_funcs.st_length.__doc__


def st_m(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_m", col)


st_m.__doc__ = pyspark_db_st_funcs.st_m.__doc__


def st_multi(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_multi", col)


st_multi.__doc__ = pyspark_db_st_funcs.st_multi.__doc__


def st_makeline(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_makeline", col)


st_makeline.__doc__ = pyspark_db_st_funcs.st_makeline.__doc__


def st_makepolygon(col1: "ColumnOrName", col2: Optional["ColumnOrName"] = None) -> "Column":
    if col2 is None:
        return _invoke_function_over_columns("st_makepolygon", col1)
    else:
        return _invoke_function_over_columns("st_makepolygon", col1, col2)


st_makepolygon.__doc__ = pyspark_db_st_funcs.st_makepolygon.__doc__


def st_ndims(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_ndims", col)


st_ndims.__doc__ = pyspark_db_st_funcs.st_ndims.__doc__


def st_npoints(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_npoints", col)


st_npoints.__doc__ = pyspark_db_st_funcs.st_npoints.__doc__


def st_numgeometries(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_numgeometries", col)


st_numgeometries.__doc__ = pyspark_db_st_funcs.st_numgeometries.__doc__


def st_perimeter(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_perimeter", col)


st_perimeter.__doc__ = pyspark_db_st_funcs.st_perimeter.__doc__


def st_point(
    col1: "ColumnOrName",
    col2: "ColumnOrName",
    col3: Optional[Union["ColumnOrName", int]] = None
) -> "Column":
    if col3 is None:
        return _invoke_function_over_columns("st_point", col1, col2)
    else:
        _col3 = lit(col3) if isinstance(col3, int) else col3
        return _invoke_function_over_columns("st_point", col1, col2, _col3)


st_point.__doc__ = pyspark_db_st_funcs.st_point.__doc__


def st_pointfromgeohash(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_pointfromgeohash", col)


st_pointfromgeohash.__doc__ = pyspark_db_st_funcs.st_pointfromgeohash.__doc__


def st_pointn(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("st_pointn", col1, _col2)


st_pointn.__doc__ = pyspark_db_st_funcs.st_pointn.__doc__


def st_reverse(col1: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_reverse", col1)


st_reverse.__doc__ = pyspark_db_st_funcs.st_reverse.__doc__


def st_rotate(col1: "ColumnOrName", col2: Union["ColumnOrName", float]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, float) else col2
    return _invoke_function_over_columns("st_rotate", col1, _col2)


st_rotate.__doc__ = pyspark_db_st_funcs.st_rotate.__doc__


def st_removepoint(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("st_removepoint", col1, _col2)


st_removepoint.__doc__ = pyspark_db_st_funcs.st_removepoint.__doc__


def st_touches(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_touches", col1, col2)


st_touches.__doc__ = pyspark_db_st_funcs.st_touches.__doc__


def st_scale(
    col1: "ColumnOrName",
    col2: Union["ColumnOrName", float],
    col3: Union["ColumnOrName", float],
    col4: Optional[Union["ColumnOrName", float]] = None
) -> "Column":
    _col2 = lit(col2) if isinstance(col2, float) else col2
    _col3 = lit(col3) if isinstance(col3, float) else col3
    if col4 is None:
        return _invoke_function_over_columns("st_scale", col1, _col2, _col3)
    else:
        _col4 = lit(col4) if isinstance(col4, float) else col4
        return _invoke_function_over_columns("st_scale", col1, _col2, _col3, _col4)


st_scale.__doc__ = pyspark_db_st_funcs.st_scale.__doc__


def st_setpoint(
    col1: "ColumnOrName",
    col2: Union["ColumnOrName", int],
    col3: "ColumnOrName"
) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("st_setpoint", col1, _col2, col3)


st_setpoint.__doc__ = pyspark_db_st_funcs.st_setpoint.__doc__


def st_setsrid(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("st_setsrid", col1, _col2)


st_setsrid.__doc__ = pyspark_db_st_funcs.st_setsrid.__doc__


def st_simplify(col1: "ColumnOrName", col2: Union["ColumnOrName", float]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, float) else col2
    return _invoke_function_over_columns("st_simplify", col1, _col2)


st_simplify.__doc__ = pyspark_db_st_funcs.st_simplify.__doc__


def st_srid(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_srid", col)


st_srid.__doc__ = pyspark_db_st_funcs.st_srid.__doc__


def st_startpoint(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_startpoint", col)


st_startpoint.__doc__ = pyspark_db_st_funcs.st_startpoint.__doc__


def st_transform(col1: "ColumnOrName", col2: Union["ColumnOrName", int]) -> "Column":
    _col2 = lit(col2) if isinstance(col2, int) else col2
    return _invoke_function_over_columns("st_transform", col1, _col2)


st_transform.__doc__ = pyspark_db_st_funcs.st_transform.__doc__


def st_translate(
    col1: "ColumnOrName",
    col2: Union["ColumnOrName", float],
    col3: Union["ColumnOrName", float],
    col4: Optional[Union["ColumnOrName", float]] = None
) -> "Column":
    _col2 = lit(col2) if isinstance(col2, float) else col2
    _col3 = lit(col3) if isinstance(col3, float) else col3
    if col4 is None:
        return _invoke_function_over_columns("st_translate", col1, _col2, _col3)
    else:
        _col4 = lit(col4) if isinstance(col4, float) else col4
        return _invoke_function_over_columns("st_translate", col1, _col2, _col3, _col4)


st_translate.__doc__ = pyspark_db_st_funcs.st_translate.__doc__


def st_union(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_union", col1, col2)


st_union.__doc__ = pyspark_db_st_funcs.st_union.__doc__


def st_union_agg(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_union_agg", col)


st_union_agg.__doc__ = pyspark_db_st_funcs.st_union_agg.__doc__


def st_within(col1: "ColumnOrName", col2: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_within", col1, col2)


st_within.__doc__ = pyspark_db_st_funcs.st_within.__doc__


def st_x(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_x", col)


st_x.__doc__ = pyspark_db_st_funcs.st_x.__doc__


def st_xmax(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_xmax", col)


st_xmax.__doc__ = pyspark_db_st_funcs.st_xmax.__doc__


def st_xmin(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_xmin", col)


st_xmin.__doc__ = pyspark_db_st_funcs.st_xmin.__doc__


def st_y(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_y", col)


st_y.__doc__ = pyspark_db_st_funcs.st_y.__doc__


def st_ymax(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_ymax", col)


st_ymax.__doc__ = pyspark_db_st_funcs.st_ymax.__doc__


def st_ymin(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_ymin", col)


st_ymin.__doc__ = pyspark_db_st_funcs.st_ymin.__doc__


def st_z(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_z", col)


st_z.__doc__ = pyspark_db_st_funcs.st_z.__doc__


def st_zmax(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_zmax", col)


st_zmax.__doc__ = pyspark_db_st_funcs.st_zmax.__doc__


def st_zmin(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("st_zmin", col)


st_zmin.__doc__ = pyspark_db_st_funcs.st_zmin.__doc__


def to_geography(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("to_geography", col)


to_geography.__doc__ = pyspark_db_st_funcs.to_geography.__doc__


def to_geometry(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("to_geometry", col)


to_geometry.__doc__ = pyspark_db_st_funcs.to_geometry.__doc__


def try_to_geography(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("try_to_geography", col)


try_to_geography.__doc__ = pyspark_db_st_funcs.try_to_geography.__doc__


def try_to_geometry(col: "ColumnOrName") -> "Column":
    return _invoke_function_over_columns("try_to_geometry", col)


try_to_geometry.__doc__ = pyspark_db_st_funcs.try_to_geometry.__doc__


def _test() -> None:
    import sys
    import doctest
    from pyspark.sql import SparkSession as PySparkSession
    import pyspark.databricks.sql.connect.functions

    globs = pyspark.databricks.sql.connect.st_functions.__dict__.copy()

    globs["spark"] = (
        PySparkSession.builder.appName("databricks.sql.connect.st_functions tests")
        .remote("local[4]")
        .getOrCreate()
    )

    (failure_count, test_count) = doctest.testmod(
        pyspark.databricks.sql.connect.st_functions,
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
