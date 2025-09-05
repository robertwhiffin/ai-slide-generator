#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2025-present Databricks, Inc.
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

"""
NOTE: THIS IS A COPY OF THE FILE `PostImportHook.py` FROM universe. This file is copied here to
replicate the post-import hook functionality in the notebook environment in UDFs.

NOTE(smacke): since the below note, this file has been modified to work with Python 3.12, and the
contents are no longer closely following those of wrapt anymore.

NOTE(databricks): The contents of this file have been inlined from the wrapt package's source code
https://github.com/GrahamDumpleton/wrapt/blob/1.12.1/src/wrapt/importer.py. We inline with the goals
of 1) avoiding introducing a 'wrapt' dependency into DBR and 2) allowing for rapid modifications of
the post-import hook logic in this file. Some modifications, have been made in order to inline functions
from dependent wrapt submodules rather than importing them.

This module implements a post import hook mechanism styled after what is described in PEP-369. Note that
it doesn't cope with modules being reloaded.
It also extends the functionality to support custom hooks for import errors (as opposed to only successful imports).
"""
from __future__ import annotations
import functools
import logging
import sys
import threading
import traceback
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import find_spec
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, Literal, Sequence, overload

if TYPE_CHECKING:
    ModuleHook = Callable[[ModuleType], Any]
    ModuleNameHook = Callable[[str], Any]
    ModuleHookDict = dict[str, list[ModuleHook]]
    ModuleNameHookDict = dict[str, list[ModuleNameHook]]

logger = logging.getLogger(__name__)

# The dictionary registering any post import hooks to be triggered once
# the target module has been imported. Once a module has been imported
# and the hooks fired, the list of hooks recorded against the target
# module will be truncated but the list left in the dictionary. This
# acts as a flag to indicate that the module had already been imported.

_post_import_hooks: ModuleHookDict = {}
_post_import_hooks_lock = threading.RLock()

_pre_import_hooks: ModuleNameHookDict = {}
_pre_import_hooks_lock = threading.RLock()

# A dictionary for any import hook error handlers to be triggered when the
# target module import fails.

_import_error_hooks: ModuleNameHookDict = {}
_import_error_hooks_lock = threading.RLock()

_import_hook_finder_init = False

# Register a new post import hook for the target module name. This
# differs from the PEP-369 implementation in that it also allows the
# hook function to be specified as a string consisting of the name of
# the callback in the form 'module:function'. This will result in a
# proxy callback being registered which will defer loading of the
# specified module containing the callback function until required.


def _create_import_hook_from_string(name: str) -> ModuleHook:
    def import_hook(module: ModuleType) -> Any:
        module_name, function = name.split(':')
        attrs = function.split('.')
        __import__(module_name)
        callback: ModuleHook = sys.modules[module_name]  # type: ignore[assignment]
        for attr in attrs:
            callback = getattr(callback, attr)
        return callback(module)

    return import_hook


@overload
def register_generic_import_hook(hook: ModuleHook | str,
                                 name: str,
                                 hook_dict: ModuleHookDict,
                                 error_handler: Literal[False] = False,
                                 raise_if_already_registered: Literal[False] = False) -> None:
    ...


@overload
def register_generic_import_hook(hook: ModuleNameHook,
                                 name: str,
                                 hook_dict: ModuleNameHookDict,
                                 error_handler: Literal[True],
                                 raise_if_already_registered: Literal[False] = False) -> None:
    ...


@overload
def register_generic_import_hook(hook: ModuleNameHook,
                                 name: str,
                                 hook_dict: ModuleNameHookDict,
                                 raise_if_already_registered: Literal[True],
                                 error_handler: Literal[False] = False) -> None:
    ...


def register_generic_import_hook(  # type: ignore[misc]
        hook_or_spec: ModuleHook | str,
        name: str,
        hook_dict: ModuleHookDict,
        error_handler: bool = False,
        raise_if_already_registered: bool = False) -> None:
    # Create a deferred import hook if hook is a string name rather than
    # a callable function.

    if isinstance(hook_or_spec, str):
        hook = _create_import_hook_from_string(hook_or_spec)
    else:
        hook = hook_or_spec

    # Automatically install the import hook finder if it has not already
    # been installed.

    global _import_hook_finder_init
    if not _import_hook_finder_init:
        _import_hook_finder_init = True
        sys.meta_path.insert(0, ImportHookFinder())

    # Determine if any prior registration of an import hook for
    # the target modules has occurred and act appropriately.

    if (hooks := hook_dict.get(name)) is None:
        # No prior registration of import hooks for the target module. We need to check whether the module has already
        # been imported. If it and `raise_if_already_imported` is False has we fire the hook immediately and add an
        # empty list to the registry to indicate that the module has already been imported and hooks have fired. If
        # present and `raise_if_already_imported` is True, raise an error. Otherwise add the post import hook to the
        # registry.
        if (module := sys.modules.get(name)) is None:
            hook_dict[name] = [hook]
        elif raise_if_already_registered:
            raise RuntimeError(f"Post import hook for {name} already registered")
        else:
            hook_dict[name] = []
            if not error_handler:
                hook(module)
    elif not hooks:
        # A prior registration of import hooks for the target
        # module was done and the hooks already fired. Fire the hook
        # immediately.
        module = sys.modules[name]
        if not error_handler:
            hook(module)
    else:
        # A prior registration of import hooks for the target
        # module was done but the module has not yet been imported.
        hook_dict[name].append(hook)


def register_import_error_hook(hook: ModuleNameHook, name: str) -> None:
    with _import_error_hooks_lock:
        register_generic_import_hook(hook, name, _import_error_hooks, error_handler=True)


def register_post_import_hook(hook: ModuleHook, name: str) -> None:
    with _post_import_hooks_lock:
        register_generic_import_hook(hook, name, _post_import_hooks, error_handler=False)


def register_pre_import_hook(hook: ModuleNameHook, name: str) -> None:
    with _pre_import_hooks_lock:
        register_generic_import_hook(
            hook, name, _pre_import_hooks, raise_if_already_registered=True)


# Register post import hooks defined as package entry points.


def _create_import_hook_from_entrypoint(entrypoint) -> ModuleHook:
    def import_hook(module: ModuleType) -> Any:
        __import__(entrypoint.module_name)
        callback: ModuleHook = sys.modules[entrypoint.module_name]  # type: ignore[assignment]
        for attr in entrypoint.attrs:
            callback = getattr(callback, attr)
        return callback(module)

    return import_hook


def discover_post_import_hooks(group: str) -> None:
    try:
        import importlib.metadata
        entrypoints = importlib.metadata.entry_points().select(group=group)
    except (KeyError, ImportError):
        return
    for entrypoint in entrypoints:
        callback = _create_import_hook_from_entrypoint(entrypoint)
        register_post_import_hook(callback, entrypoint.name)


# Indicate that a module has been loaded. Any post import hooks which
# were registered against the target module will be invoked. If an
# exception is raised in any of the post import hooks, that will cause
# the import of the target module to fail.


def notify_module_loaded(module: ModuleType) -> None:
    if (name := getattr(module, '__name__', None)) is None:
        return
    with _post_import_hooks_lock:
        if not (hooks := _post_import_hooks.get(name)):
            return
        _post_import_hooks[name] = []
    for hook in hooks:
        hook(module)


def notify_module_import_error(module_name: str) -> None:
    # Error hooks differ from post import hooks, in that we don't clear the
    # hook as soon as it fires.
    hooks = _import_error_hooks.pop(module_name, None)
    # ensure that multiple threads can't invoke the error hooks concurrently,
    # but without locking. downside is that some thread may not see an error
    # hook but that's a small price to pay to avoid deadlock, and we're
    # guaranteed that at least one thread will call the hook anyway.
    for hook in (hooks or []):
        hook(module_name)
    if hooks is not None:
        with _import_error_hooks_lock:
            _import_error_hooks[module_name] = hooks + _import_error_hooks.get(module_name, [])


# A custom module import finder. This intercepts attempts to import
# modules and watches out for attempts to import target modules of
# interest. When a module of interest is imported, then any post import
# hooks which are registered will be invoked.


def make_patched_exec_module(
        exec_module: Callable[[ModuleType], None]) -> Callable[[ModuleType], None]:
    @functools.wraps(exec_module)
    def patched_exec_module(module: ModuleType) -> None:
        try:
            exec_module(module)
            notify_module_loaded(module)
        except (ImportError, AttributeError):
            notify_module_import_error(module.__name__)
            raise

    return patched_exec_module


def make_patched_load_module(
        load_module: Callable[[str], ModuleType]) -> Callable[[str], ModuleType]:
    @functools.wraps(load_module)
    def patched_load_module(name: str) -> ModuleType:
        try:
            module = load_module(name)
            notify_module_loaded(module)
        except (ImportError, AttributeError):
            notify_module_import_error(name)
            raise
        return module

    return patched_load_module


class ImportHookFinder(MetaPathFinder):
    def __init__(self) -> None:
        self._local = threading.local()
        self._local.in_progress = set()

    @property
    def in_progress(self) -> set[str]:
        if not hasattr(self._local, "in_progress"):
            self._local.in_progress = set()
        return self._local.in_progress

    @staticmethod
    def _find_and_possibly_instrument_spec(fullname: str) -> ModuleSpec | None:
        """
        For Python 3 we need to use find_spec().loader from the importlib.util module. It doesn't actually import the
        target module and only finds the loader. If a loader is found, we need to return our own loader which will then
        in turn call the real loader to import the module and invoke the post import hooks.
        """
        if fullname not in _post_import_hooks and fullname not in _import_error_hooks:
            return None
        try:
            spec = find_spec(fullname)
        # If an ImportError (or AttributeError) is encountered while finding the module,
        # notify the hooks for import errors
        except (ImportError, AttributeError):
            spec = None
        if spec is None:
            notify_module_import_error(fullname)
        elif (loader := getattr(spec, "loader", None)) is not None:
            if hasattr(loader, "exec_module"):
                loader.exec_module = make_patched_exec_module(  # type: ignore[method-assign]
                    loader.exec_module)
            if hasattr(loader, "load_module"):
                loader.load_module = make_patched_load_module(  # type: ignore[method-assign]
                    loader.load_module)
        return spec

    def find_spec(self,
                  fullname: str,
                  path: Sequence[str] | None = None,
                  target: ModuleType | None = None) -> ModuleSpec | None:
        # If the module being imported is not one we have registered
        # import hooks for, we can return immediately. We will
        # take no further part in the importing of this module.

        if fullname not in _post_import_hooks and fullname not in _pre_import_hooks and fullname not in _import_error_hooks:
            return None

        # When we are interested in a specific module, we will call back
        # into the import system a second time to defer to the import
        # finder that is supposed to handle the importing of the module.
        # We set an in progress flag for the target module so that on
        # the second time through we don't trigger another call back
        # into the import system and cause a infinite loop.
        if fullname in self.in_progress:
            return None

        self.in_progress.add(fullname)
        try:
            for hook in _pre_import_hooks.pop(fullname, []):
                try:
                    hook(fullname)
                except Exception:
                    logger.exception("Error calling pre-import hook for %s", fullname)
            # Now call back into the import system again.
            return self._find_and_possibly_instrument_spec(fullname)
        finally:
            self.in_progress.remove(fullname)


# Decorator for marking that a function should be called as a post
# import hook when the target module is imported.
# If error_handler is True, then apply the marked function as an import hook
# for import errors (instead of successful imports).
# It is assumed that all error hooks are added during driver start-up,
# and thus added prior to any import calls. If an error hook is added
# after a module has already failed the import, there's no guarantee
# that the hook will fire.


@overload
def when_imported(name: str,
                  error_handler: Literal[False] = False) -> Callable[[ModuleHook], ModuleHook]:
    ...


@overload
def when_imported(name: str,
                  error_handler: Literal[True]) -> Callable[[ModuleNameHook], ModuleNameHook]:
    ...


def when_imported(
        name: str, error_handler: bool = False
) -> Callable[[ModuleHook], ModuleHook] | Callable[[ModuleNameHook], ModuleNameHook]:
    if error_handler:

        def register_error_hook(hook: ModuleNameHook) -> ModuleNameHook:
            register_import_error_hook(hook, name)
            return hook

        return register_error_hook
    else:

        def register_hook(hook: ModuleHook) -> ModuleHook:
            register_post_import_hook(hook, name)
            return hook

        return register_hook


def before_imported(name: str) -> Callable[[ModuleNameHook], ModuleNameHook]:
    def register_hook(hook: ModuleNameHook) -> ModuleNameHook:
        register_pre_import_hook(hook, name)
        return hook

    return register_hook


def log_errors(f: Callable[..., Any]) -> Callable[..., Any]:
    """
    Wraps a function with error handling. If an error is raised the wrapped function will log the
    error to stderr and return.
    """

    @functools.wraps(f)
    def safe_f(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            if hasattr(f, "__name__"):
                f_name = f.__name__
            else:
                f_name = repr(f)
            print(f"Error calling {f_name}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    return safe_f
