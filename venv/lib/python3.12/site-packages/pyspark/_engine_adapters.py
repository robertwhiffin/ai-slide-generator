"""
Engine PySpark adapters.

`create_engine_pyspark.sh` creates a zip file that contains a copy of the pyspark module.

!!!!
THIS FILE IS EXCLUDED FROM rewriting in `create_engine_pyspark.sh`, hence references to "pyspark"
and "_engine_pyspark" are always preserved.
!!!!

The client environment uses `pyspark` module, however to use worker.py (to run UDFs), we need a `pyspark`
module that is compatible with the Spark operators that interact with the worker through a binary protocol.

As the client only knows `pyspark`, types and objects serialized by the client need to be converted to the
compatible types in the engine_pyspark module.
"""
import os
import importlib
from typing import Union

IS_ENGINE_PYSPARK = "_engine_pyspark.zip" in __file__
# An override to use for testing, where we want be able to import below's functions.
ENGINE_PYSPARK_OVERRIDE = os.environ.get("TEST_PYSPARK_ENGINE_PYSPARK_OVERRIDE", None)

assert "pyspark" == "p" + "yspark", "unexpected rewrite occurred - check create_engine_pyspark.sh"

# Only register adapter functions when we are running in engine_pyspark.
# Importing any of these functions must be guarded by checking IS_ENGINE_PYSPARK.
if IS_ENGINE_PYSPARK or ENGINE_PYSPARK_OVERRIDE:

    class _LazyLoader:
        """
        Delay image loads to avoid circular imports.
        """

        def __init__(self, modname):
            self._modname = modname
            self._mod = None

        def __getattr__(self, attr):
            if self._mod is None:
                self._mod = importlib.import_module(self._modname)
            return getattr(self._mod, attr)

    client_pyspark = _LazyLoader("pyspark")

    from builtins import (
        isinstance as builtin_isinstance,
        issubclass as builtin_issubclass,
        type as builtin_type,
    )

    _convertible_modules = ("pyspark.sql.types", "pyspark.sql.datasource", "pyspark.sql.udtf", "pyspark.errors.exceptions.base")
    _target_modules = ("_engine_pyspark.sql.types", "_engine_pyspark.sql.datasource", "_engine_pyspark.sql.udtf", "_engine_pyspark.errors.exceptions.base")

    client_pyspark_errors = _LazyLoader("pyspark.errors.exceptions.base")
    client_pyspark_datasource = _LazyLoader("pyspark.sql.datasource")
    client_pyspark_sql_udtf = _LazyLoader("pyspark.sql.udtf")
    client_pyspark_sql_types = _LazyLoader("pyspark.sql.types")

    def _converted_cls(cls):
        """
        Convert the type of an object to the engine_pyspark type, if conversion applies.
        """
        import _engine_pyspark.sql.types
        import _engine_pyspark.sql.datasource
        import _engine_pyspark.sql.udtf
        import _engine_pyspark.errors.exceptions.base

        if cls.__module__ == "pyspark.sql.types":
            return _engine_pyspark.sql.types.__dict__[cls.__name__]
        elif cls.__module__ == "pyspark.sql.datasource":
            return _engine_pyspark.sql.datasource.__dict__[cls.__name__]
        elif cls.__module__ == "pyspark.sql.udtf":
            return _engine_pyspark.sql.udtf.__dict__[cls.__name__]
        elif cls.__module__ == "pyspark.errors.exceptions.base":
            return _engine_pyspark.errors.exceptions.base.__dict__[cls.__name__]
        else:
            return cls

    def type(obj):
        """
        Returns the type of an object, with special handling for client pyspark sql/datasources types
        translating into _engine_pyspark types.
        """
        tp = builtin_type(obj)
        return _converted_cls(tp)

    def convert_return_type(return_type_instance):
        # delay import to avoid circular import
        from _engine_pyspark.sql.types import _parse_datatype_json_string

        return_type = builtin_type(return_type_instance)  # original type, without conversion

        if return_type.__module__ == "pyspark.sql.types":
            return _parse_datatype_json_string(return_type_instance.json())
        else:
            return return_type_instance

    def setup_pyspark_pickle_serializer():
        import sys

        # Short-circuit the import of cloudpickle to the client cloudpickle module.
        # As per https://github.com/cloudpipe/cloudpickle/blob/c025de75715cd2f22f650d1b4bbb8559e8eaac46/tests/test_backward_compat.py#L1-L11,
        # > Cloudpickle does not officially support reading pickles files generated with an older
        # > version of cloudpickle than the one used to read the said pickles.
        # This avoids an error with signature:
        #   `Can't get attribute '_function_setstate' on <module 'pyspark.cloudpickle.cloudpickle'
        sys.modules["_engine_pyspark.cloudpickle"] = importlib.import_module("pyspark.cloudpickle")
        sys.modules["_engine_pyspark.cloudpickle.cloudpickle"] = importlib.import_module(
            "pyspark.cloudpickle.cloudpickle"
        )

    def _extract_bases(obj_or_type):
        if builtin_isinstance(obj_or_type, builtin_type):
            cls = obj_or_type
        else:
            cls = obj_or_type.__class__
        return cls, cls.mro()

    def _specialized_isinstance(obj_or_type, clsinfo):
        cls, bases = _extract_bases(obj_or_type)
        if convertible_bases := [c for c in bases if c.__module__ in _convertible_modules]:
            converted_bases = [_converted_cls(c) for c in convertible_bases]
            return cls in converted_bases or any(
                clsinfo.__subclasscheck__(cls) for cls in converted_bases
            )
        else:
            return False

    def _isinstance(obj_or_type, clsinfo):
        if builtin_type(clsinfo) == tuple:
            return any(_isinstance(obj_or_type, c) for c in clsinfo)
        if builtin_type(clsinfo) == Union:
            return any(_isinstance(obj_or_type, c) for c in clsinfo.args)
        if clsinfo is type:  # account for the above `type` "override"
            return _isinstance(obj_or_type, builtin_type)
        # if the type is a client pyspark type, use the specialized version.
        if clsinfo.__module__ in _target_modules:
            return _specialized_isinstance(obj_or_type, clsinfo)
        else:
            return False

    def isinstance(obj_or_type, clsinfo):
        """
        Is `obj` an instance of `cls`, with special handling for client pyspark sql types,
        to allow functions to return client pyspark sql/datasource types, despite running in engine_pyspark.
        """
        # ideally, we would not override type, but we need it in a few places, so we need to handle it here.
        if clsinfo is type:
            return isinstance(obj_or_type, builtin_type)
        elif builtin_isinstance(obj_or_type, clsinfo):
            return True
        elif _isinstance(obj_or_type, clsinfo):
            return True
        else:
            return False

    def issubclass(cls, clsinfo):
        """
        Is `cls` a subclass of `clsinfo`, with special handling for client pyspark sql types,
        to allow functions to return client pyspark sql/datasource types, despite running in engine_pyspark.
        """
        # ideally, we would not override type, but we need it in a few places, so we need to handle it here.
        if clsinfo is type:
            return isinstance(cls, builtin_type)
        elif builtin_issubclass(cls, clsinfo):
            return True
        elif _isinstance(cls, clsinfo):
            return True
        else:
            return False

    def class_is_present(package, class_name):
        try:
            module = importlib.import_module(package)
            return hasattr(module, class_name)
        except ImportError:
            return False

    def patch_transform_with_state_udf_utils(eval_type, f):
        # In client image v1, TransformWithStateInPandasUdfUtils are not present,
        # so there's no need to patch.
        if not class_is_present("pyspark.sql.streaming.stateful_processor_util",
                                "TransformWithStateInPandasUdfUtils"):
            return f

        from _engine_pyspark.util import PythonEvalType
        from pyspark.sql.streaming.stateful_processor_util import TransformWithStateInPandasUdfUtils as ClientTransformWithStateInPandasUdfUtils
        from _engine_pyspark.sql.streaming.stateful_processor_util import TransformWithStateInPandasUdfUtils as EngineTransformWithStateInPandasUdfUtils

        # TWS and TWSIP send their python functions from pyspark.sql.connect.group in the following
        # pattern:
        #   udf_util = TransformWithStateInPandasUdfUtils(statefulProcessor, timeMode)
        #   udf_obj = UserDefinedFunction(udf_util.transformWithStateUDF, ...)
        #   plan.TransformWithStateInPandas(..., function=udf_obj, ...)
        #
        # This leads to sending a reference to client UdfUtils class, which does not correctly interact
        # with engine_pyspark, due to mismatching types (particularly different state Enums).
        #
        # To rectify this, we replace the client-side UdfUtils class with the engine_pyspark version.

        # Check if f is a bound method of ClientTransformWithStateInPandasUdfUtils.
        # Future implementations may not send ClientTransformWithStateInPandasUdfUtils, but the plain
        # _stateful_processor.
        if hasattr(f, "__self__") and isinstance(f.__self__, ClientTransformWithStateInPandasUdfUtils):
            func_self = f.__self__
            engine_utils = EngineTransformWithStateInPandasUdfUtils(
                func_self._stateful_processor,
                func_self._time_mode
            )
            if eval_type == PythonEvalType.SQL_TRANSFORM_WITH_STATE_PANDAS_UDF:
                return engine_utils.transformWithStateUDF
            elif eval_type == PythonEvalType.SQL_TRANSFORM_WITH_STATE_PANDAS_INIT_STATE_UDF:
                return engine_utils.transformWithStateWithInitStateUDF
            elif eval_type == PythonEvalType.SQL_TRANSFORM_WITH_STATE_PYTHON_ROW_UDF:
                return engine_utils.transformWithStateUDF
            elif eval_type == PythonEvalType.SQL_TRANSFORM_WITH_STATE_PYTHON_ROW_INIT_STATE_UDF:
                return engine_utils.transformWithStateWithInitStateUDF
            else:
                assert False, "Unsupported eval type: %s" % eval_type
        else:
            return f

    def engine_pyspark_function_converter(eval_type, f):
        """
        Convert a function to the engine_pyspark type, if conversion applies.
        """
        f = patch_transform_with_state_udf_utils(eval_type, f)
        return f

    def is_client_image_v1():
        """
        Returns True if engine pyspark is running with client image v1.
        """
        import sys
        return sys.version_info < (3, 11)
