# -*- coding: utf-8 -*-
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import functools
import inspect
import threading
import time
from types import ModuleType, FunctionType
from typing import Optional, Tuple, List, Callable, Any, Type
from pyspark.taskcontext import TaskContext


__all__: List[str] = []

_local = threading.local()


def _wrap_function(
    module_name: str, class_name: str, function_name: str, func: Callable, logger: Any
) -> Callable:
    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if hasattr(_local, "logging") and _local.logging:
            # no need to log since this should be internal call.
            return func(*args, **kwargs)
        _local.logging = True
        try:
            start = time.perf_counter()
            try:
                res = func(*args, **kwargs)
                logger.log_success(
                    module_name, class_name, function_name, time.perf_counter() - start, signature
                )
                return res
            except Exception as ex:
                logger.log_failure(
                    module_name,
                    class_name,
                    function_name,
                    ex,
                    time.perf_counter() - start,
                    signature,
                )
                raise
        finally:
            _local.logging = False

    return wrapper


def _wrap_property(
    module_name: str, class_name: str, property_name: str, prop: Any, logger: Optional[Any]
) -> Any:
    @property  # type: ignore[misc]
    def wrapper(self: Any) -> Any:
        if hasattr(_local, "logging") and _local.logging:
            # no need to log since this should be internal call.
            return prop.fget(self)
        _local.logging = True
        try:
            if logger is None:
                return prop.fget(self)

            start = time.perf_counter()
            try:
                res = prop.fget(self)
                logger.log_success(
                    module_name, class_name, property_name, time.perf_counter() - start
                )
                return res
            except Exception as ex:
                logger.log_failure(
                    module_name, class_name, property_name, ex, time.perf_counter() - start
                )
                raise
        finally:
            _local.logging = False

    wrapper.__doc__ = prop.__doc__

    if prop.fset is not None:
        wrapper = wrapper.setter(  # type: ignore[attr-defined]
            _wrap_function(module_name, class_name, prop.fset.__name__, prop.fset, logger)
        )

    return wrapper


def _wrap_cached_property(
    module_name: str,
    class_name: str,
    property_name: str,
    prop: functools.cached_property,
    logger: Optional[Any],
) -> Any:
    class wrapper:
        def __init__(self, cached_property: functools.cached_property) -> None:
            self._cached_property = cached_property

        def __get__(self, instance: Any, owner: Optional[Type[Any]] = None) -> Any:
            if hasattr(_local, "logging") and _local.logging:
                # no need to log since this should be internal call.
                return self._cached_property.__get__(instance, owner)

            _local.logging = True
            try:
                if logger is None:
                    return self._cached_property.__get__(instance, owner)

                start = time.perf_counter()
                try:
                    res = self._cached_property.__get__(instance, owner)
                    logger.log_success(
                        module_name, class_name, property_name, time.perf_counter() - start
                    )
                    return res
                except Exception as ex:
                    logger.log_failure(
                        module_name, class_name, property_name, ex, time.perf_counter() - start
                    )
                    raise
            finally:
                _local.logging = False

    return wrapper(prop)


def _wrap_missing_function(
    class_name: str, function_name: str, func: Callable, original: Any, logger: Any
) -> Any:
    if not hasattr(original, function_name):
        return func

    signature = inspect.signature(getattr(original, function_name))

    is_deprecated = func.__name__ == "deprecated_function"

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        finally:
            logger.log_missing(class_name, function_name, is_deprecated, signature)

    return wrapper


def _wrap_missing_property(class_name: str, property_name: str, prop: Any, logger: Any) -> Any:
    is_deprecated = prop.fget.__name__ == "deprecated_property"

    @property  # type: ignore[misc]
    def wrapper(self: Any) -> Any:
        try:
            return prop.fget(self)
        finally:
            logger.log_missing(class_name, property_name, is_deprecated)

    return wrapper


_is_wrapped = {}


def _wrap_attr(obj: object, name: str, wrapped_val: Any) -> None:
    setattr(obj, name, wrapped_val)
    _is_wrapped[wrapped_val] = True


def _attach(
    logger: Any,
    modules: List[ModuleType],
    classes: List[Type[Any]],
    class_property_allow_list: Optional[List[Type[Any]]],
    missings: List[Tuple[Type[Any], Type[Any]]],
    private_function_allow_list: List[FunctionType] = [],
) -> None:
    special_functions = set(
        [
            "__init__",
            "__repr__",
            "__str__",
            "_repr_html_",
            "__len__",
            "__getitem__",
            "__setitem__",
            "__getattr__",
            "__enter__",
            "__exit__",
        ]
    )

    # Modules
    for target_module in modules:
        target_name = target_module.__name__.split(".")[-1]
        for name in getattr(target_module, "__all__"):
            func = getattr(target_module, name)
            if (not inspect.isfunction(func)) or (func in _is_wrapped):
                continue
            _wrap_attr(
                target_module, name, _wrap_function(target_name, target_name, name, func, logger)
            )

    # Classes
    for target_class in classes:
        for name, func in inspect.getmembers(target_class, inspect.isfunction):
            if (name.startswith("_") and name not in special_functions) or (func in _is_wrapped):
                continue
            try:
                isstatic = isinstance(inspect.getattr_static(target_class, name), staticmethod)
            except AttributeError:
                isstatic = False
            wrapped_function = _wrap_function(
                target_class.__module__, target_class.__name__, name, func, logger
            )
            _wrap_attr(
                target_class, name, staticmethod(wrapped_function) if isstatic else wrapped_function
            )

        for name, prop in inspect.getmembers(target_class, lambda o: isinstance(o, property)):
            if name.startswith("_") or (prop in _is_wrapped):
                continue

            optional_logger = None
            if (class_property_allow_list is None) or (prop in class_property_allow_list):
                optional_logger = logger

            _wrap_attr(
                target_class,
                name,
                _wrap_property(
                    target_class.__module__,
                    target_class.__name__,
                    name,
                    prop,
                    optional_logger,
                ),
            )

        for name, prop in inspect.getmembers(
            target_class, lambda o: isinstance(o, functools.cached_property)
        ):
            if name.startswith("_") or (prop in _is_wrapped):
                continue

            optional_logger = None
            if (class_property_allow_list is None) or (prop in class_property_allow_list):
                optional_logger = logger

            _wrap_attr(
                target_class,
                name,
                _wrap_cached_property(
                    target_class.__module__,
                    target_class.__name__,
                    name,
                    prop,
                    optional_logger,
                ),
            )

    # Missings
    for original, missing in missings:
        for name, func in inspect.getmembers(missing, inspect.isfunction):
            setattr(
                missing,
                name,
                _wrap_missing_function(original.__name__, name, func, original, logger),
            )

        for name, prop in inspect.getmembers(missing, lambda o: isinstance(o, property)):
            setattr(missing, name, _wrap_missing_property(original.__name__, name, prop, logger))

    # BEGIN-EDGE
    # Functions
    for func in private_function_allow_list:
        target_module = inspect.getmodule(func)
        target_name = target_module.__name__.split(".")[-1]
        name = func.__name__
        if (not inspect.isfunction(func)) or (func in _is_wrapped):
            continue
        _wrap_attr(
            target_module, name, _wrap_function(target_name, target_name, name, func, logger)
        )
    # END-EDGE


def _auto_patch_spark(
    modules: List[ModuleType],
    classes: List[Type[Any]],
    class_property_allow_list: Optional[List[Type[Any]]],
    private_function_allow_list: List[FunctionType] = [],
) -> None:
    import logging

    # Attach a usage logger.
    if TaskContext.get() is None:
        try:
            from pyspark.databricks import usage_logger

            logger = usage_logger.get_logger()

            _attach(
                logger, modules, classes, class_property_allow_list, [], private_function_allow_list
            )
        except Exception as e:
            logger = logging.getLogger("pyspark.usage_logger")
            logger.warning(
                "Tried to attach usage logger `{}`, but an exception was raised: {}".format(
                    usage_logger.__name__, str(e)
                )
            )


# BEGIN-EDGE
def _instrument_after_spark_context_init(
    modules: List[ModuleType],
    classes: List[Type[Any]],
    class_property_allow_list: Optional[List[Type[Any]]],
    private_function_allow_list: List[FunctionType] = [],
) -> None:
    """
    Instrument modules and classes after spark context is initialized to
    avoid unnecessary instrumentation when non-driver code imports pyspark modules
    without an active SparkContext.
    """

    from pyspark import SparkContext

    def instrument_hook():
        if SparkContext._jvm.PythonUtils.isPySparkInstrumentationEnabled(
            SparkContext._active_spark_context._jsc,
        ):
            _auto_patch_spark(
                modules, classes, class_property_allow_list, private_function_allow_list
            )

    SparkContext._add_after_init_hook(instrument_hook)


# END-EDGE
