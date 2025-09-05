"""
When WSFS is enabled, we modify the sys.path to include the path of the
notebook being run. It has been observed that imports of certain
modules (ex. import pandas)  will trigger a `opendir` request to
every item in the sys.path, which in turn means that we will
trigger an operation in the WSFS FUSE daemon (which in turns
causes an RPC to hit the Databricks CP).

For more information on how the importer works, see:
# flake8 noqa E501
https://docs.python.org/3/reference/import.html#path-entry-finders

This class implements a custom path hook which will inspect the
callstack and check to see if an import comes from "user-code"
(ex. from another WSFS file or a notebook command). Otherwise,
we will reject the import (which prevents the `opendir`
from reaching the FUSE daemon in the first place).

"""
import sys
import inspect
import importlib.abc


from pyspark._engine_adapters import IS_ENGINE_PYSPARK

if IS_ENGINE_PYSPARK:
    from pyspark._engine_adapters import client_pyspark

    client_pyspark_path = client_pyspark.__path__[0]

    def is_engine_pyspark_import(filename):
        return filename.startswith(client_pyspark_path)


class WsfsImportHook(importlib.abc.PathEntryFinder):
    @classmethod
    def __get_file_finder(cls, path):
        for hook in sys.path_hooks:
            if not isinstance(hook, cls):
                try:
                    return hook(path)
                except ImportError:
                    continue

        raise ImportError

    def __init__(
        self, path, site_packages=None, max_recursion_depth=100, test_prefix=""
    ):  # noqa 501
        # We can only handle importing Files in Repos/Workspace.
        # On GCP and Nephos, /Workspace is a symlink to /.fuse-mounts/wsfs where
        # wsfs is actually mounted. This leads to some system modules attempting to
        # import using the /.fuse-mounts/wsfs path and avoiding the hook if it's only
        # registered for /Workspace.
        valid_paths = ["/Workspace", "/.fuse-mounts/wsfs"]
        if not any(path.startswith(f"{test_prefix}{p}/") for p in valid_paths):
            raise ImportError

        self.__finder = self.__get_file_finder(path)
        self.__max_recursion_depth = max_recursion_depth
        self.__site_packages = site_packages or [
            item
            for item in sys.path
            if "site-packages" in item or "dist-packages" in item  # noqa E501
        ]

    def get_filename(self, curframe):
        return curframe.f_code.co_filename

    def __is_user_import(self):
        try:
            f = inspect.currentframe()
            num_items_processed = 0
            while f is not None:
                # We haven't found a site-package yet, probably from an user.
                if num_items_processed >= self.__max_recursion_depth:
                    return True

                filename = self.get_filename(f)
                # Is this import coming from the Ipython shell
                # (i.e User Notebook) directly?
                if "IPython/core/interactiveshell.py" in filename:
                    return True
                is_site_packages = any(
                    filename.startswith(package) for package in self.__site_packages  # noqa E501
                )

                # Skip over client pyspark, as we at the minimum pass through client's
                # cloudpickle to ensure that the worker can load the module (see
                # _engine_adapters.setup_pyspark_pickle_serializer()).
                is_client_pyspark = IS_ENGINE_PYSPARK and is_engine_pyspark_import(filename)

                if is_site_packages and not is_client_pyspark:
                    return False

                num_items_processed += 1
                f = f.f_back

            # none of the stack frames are from a site-package,
            # probably directly from the user.
            return True
        except Exception as e:
            # Swallow exception. This should be non-blocking
            print("An exception when checking if user import: ", e)
            return False

    """
    Implements the find_spec method as described in:
    # noqa: E501
    https://docs.python.org/3/library/importlib.html#importlib.abc.PathEntryFinder.find_spec.

    This function should only be called when importing modules under the
    /Workspace prefix. If invoked from user code (we define user code as not being invoked
    from a package under site-packages/dist-packages), then we invoke the actual
    finder (in most cases the FileFinder.path_hook) which findes the spec
    for the given module.

    Otherwise we return None, which indicates that a spec wasn't found (and thus we are
    unable to load the module). Since this hook is inserted before the FileFinder.path_hook, it
    prevents the import for this particular path from hitting the FUSE daemon.
    """

    def find_spec(self, fullname, target=None):
        try:
            if self.__is_user_import():
                m = self.__finder.find_spec(fullname, target)
                return m
            else:
                # refuse to attempt to load modules
                return None
        except Exception as e:
            # Swallow exception. This should be non-blocking
            print("An exception occured when attemptng to find the spec: ", e)
            return None
