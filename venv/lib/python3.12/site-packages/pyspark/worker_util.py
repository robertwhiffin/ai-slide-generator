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

"""
Util functions for workers.
"""
import importlib
from inspect import currentframe, getframeinfo
import os
import glob  # Edge
import sys
from typing import Any, IO
import warnings

# 'resource' is a Unix specific module.
has_resource_module = True
try:
    import resource
except ImportError:
    has_resource_module = False

from pyspark.accumulators import _accumulatorRegistry
from pyspark.util import is_remote_only
from pyspark.errors import PySparkRuntimeError
from pyspark.util import local_connect_and_auth
from pyspark.serializers import (
    read_bool,
    read_int,
    read_long,
    write_int,
    FramedSerializer,
    UTF8Deserializer,
    CPickleSerializer,
)

# BEGIN-EDGE
from pyspark.wsfs_import_hook import WsfsImportHook
from pyspark.databricks.wsfs.wsfs_path_finder import register_wsfs_path_finder

# END-EDGE

pickleSer = CPickleSerializer()
utf8_deserializer = UTF8Deserializer()


def add_path(path: str, pos: int = 1) -> None:  # Edge
    # worker can be used, so do not add path multiple times
    if path not in sys.path:
        # overwrite system packages
        sys.path.insert(pos, path)  # Edge


def read_command(serializer: FramedSerializer, file: IO) -> Any:
    if not is_remote_only():
        from pyspark.core.broadcast import Broadcast

    command = serializer._read_with_length(file)
    if not is_remote_only() and isinstance(command, Broadcast):
        command = serializer.loads(command.value)
    return command


def check_python_version(infile: IO) -> None:
    """
    Check the Python version between the running process and the one used to serialize the command.
    """
    version = utf8_deserializer.loads(infile)
    worker_version = "%d.%d" % sys.version_info[:2]
    if version != worker_version:
        raise PySparkRuntimeError(
            errorClass="PYTHON_VERSION_MISMATCH",
            messageParameters={
                "worker_version": worker_version,
                "driver_version": str(version),
            },
        )


def setup_memory_limits(memory_limit_mb: int) -> None:
    """
    Sets up the memory limits.

    If memory_limit_mb > 0 and `resource` module is available, sets the memory limit.
    Windows does not support resource limiting and actual resource is not limited on MacOS.
    """
    if memory_limit_mb > 0 and has_resource_module:
        total_memory = resource.RLIMIT_AS
        try:
            (soft_limit, hard_limit) = resource.getrlimit(total_memory)
            msg = "Current mem limits: {0} of max {1}\n".format(soft_limit, hard_limit)
            print(msg, file=sys.stderr)

            # convert to bytes
            new_limit = memory_limit_mb * 1024 * 1024

            if soft_limit == resource.RLIM_INFINITY or new_limit < soft_limit:
                msg = "Setting mem limits to {0} of max {1}\n".format(new_limit, new_limit)
                print(msg, file=sys.stderr)
                resource.setrlimit(total_memory, (new_limit, new_limit))

        except (resource.error, OSError, ValueError) as e:
            # not all systems support resource limits, so warn instead of failing
            current = currentframe()
            lineno = getframeinfo(current).lineno + 1 if current is not None else 0
            if "__file__" in globals():
                print(
                    warnings.formatwarning(
                        "Failed to set memory limit: {0}".format(e),
                        ResourceWarning,
                        __file__,
                        lineno,
                    ),
                    file=sys.stderr,
                )


def setup_spark_files(infile: IO) -> None:
    """
    Set up Spark files, archives, and pyfiles.
    """
    # BEGIN-EDGE
    # fetch the python isolated library name prefix
    isolated_library_prefix = utf8_deserializer.loads(infile)
    # fetch the python virtualenv rootdir name
    virtualenv_root_dir = utf8_deserializer.loads(infile)

    # When a UDF is created, we serialize any sys.path entries
    # beginning with /Workspace that currently exist on the driver.
    # Our custom handling of these sys.path entries allows the
    # UDF deserialization to import python modules from
    # Workspace Filesystem (which is mounted at /Workspace).
    # These Workspace sys.path entries are serialized in the
    # python_includes list, so we have custom handling for any
    # python_includes entry that starts with /Workspace.
    workspace_sys_paths = []
    # END-EDGE

    # fetch name of workdir
    spark_files_dir = utf8_deserializer.loads(infile)

    if not is_remote_only():
        from pyspark.core.files import SparkFiles

        SparkFiles._root_directory = spark_files_dir
        SparkFiles._is_running_on_worker = True

    # fetch names of includes (*.zip and *.egg files) and construct PYTHONPATH
    add_path(spark_files_dir)  # *.py files that were added will be copied here
    num_python_includes = read_int(infile)
    for _ in range(num_python_includes):
        filename = utf8_deserializer.loads(infile)

        # BEGIN-EDGE
        if isolated_library_prefix in filename:
            # path for isolated library is always inserted at the begining of paths
            add_path(os.path.join(spark_files_dir, filename))
        elif filename == "/Workspace" or filename.startswith("/Workspace/"):
            # Extract any python_includes entry that is used for importing from
            # Workspace Filesystem for custom handling.
            workspace_sys_paths.append(filename)
        else:
            # for cluster wide library, it needs to be added after all the isolated library
            # and the virtualenv site-package (if a virtualenv is created). This is done by
            # traverse the system path in a reverse order, stop at the first isolated library
            # path or directory under the virtualenv dir, and then insert the library path
            # after the current path.
            path_index = 1
            for i, cpath in reversed(list(enumerate(sys.path))):
                (tmpdir, tmpfile) = os.path.split(cpath)
                if tmpfile.startswith(isolated_library_prefix) or (virtualenv_root_dir in tmpdir):
                    path_index = i + 1
                    break
            add_path(os.path.join(spark_files_dir, filename), path_index)
        # END-EDGE

    # BEGIN-EDGE
    db_session_uuid = os.environ.get("DB_SESSION_UUID", None)
    aether_multi_driver_enabled = read_bool(infile)
    aether_multi_driver_notebook_libraries_enabled = read_bool(infile)
    driver_id = utf8_deserializer.loads(infile)
    is_driver = read_bool(infile)
    nfs_dir = "/local_disk0/.ephemeral_nfs"
    if not is_driver or "AETHER_MULTI_DRIVER_TESTING" in os.environ:
        # TODO(SASP-4994): See AetherPysparkPythonEnvUDFSuite for testing bypass
        # nfs_dir only changes for executors even in multi-driver scenarios as each driver only has
        # access to its own nfs directory at /local_disk0/.ephemeral_nfs.
        if aether_multi_driver_enabled and aether_multi_driver_notebook_libraries_enabled:
            if driver_id == "driver":
                print("Driver id unavailable in Aether multi-driver, "
                      "falling back to default NFS artifact path", file=sys.stderr)
            else:
                nfs_dir = f"/local_disk0/.ephemeral_nfs_multi_driver/{driver_id}"
    artifacts_dir = f"{nfs_dir}/artifacts/{db_session_uuid}/pyfiles"
    if artifacts_dir and os.path.exists(artifacts_dir):
        python_files_dir = artifacts_dir
        add_path(python_files_dir)
        for match in glob.glob(python_files_dir + "/*.zip"):
            add_path(match)
    # END-EDGE

    invalidate_caches()  # Edge

    # BEGIN-EDGE
    # this is only set if Files is enabled in Repos or Workspace
    notebook_dir = os.environ.get("PYTHON_NOTEBOOK_PATH", "")
    if notebook_dir != "":
        prefix = os.environ.get("WSFS_TEST_DIR", "")

        notebook_workspace_sys_paths = []

        # For DBR 14+ we will default set the CWD to the notebook directory if WSFS is enabled.
        default_enable_cwd = os.environ.get("PYTHON_DEFAULT_CWD", "false")
        repo_path = os.environ.get("PYTHON_REPO_PATH", "")
        dir_path = prefix + notebook_dir
        if default_enable_cwd == "true" or repo_path != "":
            change_cwd_to_notebook_dir(dir_path)

        if repo_path != "":
            # Determine the workspace sys path entries that should be set
            # based on the notebook path.
            notebook_workspace_sys_paths.append(dir_path)
            # Add the repo dir too.
            repo_path = prefix + repo_path
            if repo_path != dir_path:
                notebook_workspace_sys_paths.append(repo_path)

            for i in range(len(sys.path)):
                # replace the placeholder set in PythonDriverLocal
                if sys.path[i] == "/WSFS_NOTEBOOK_DIR":
                    sys.path[i] = notebook_workspace_sys_paths[0]

                    if len(notebook_workspace_sys_paths) == 2:
                        sys.path.insert(i + 1, notebook_workspace_sys_paths[1])
                    break
        else:
            # Notebook is not in a repo.
            # PYTHON_NOTEBOOK_DIR is set implies that Files in Workspace is enabled
            # we want to put the python path at the end in this case
            remove_wsfs_path_placeholder()
            sys_path = prefix + notebook_dir
            notebook_workspace_sys_paths.append(sys_path)
            add_path(sys_path, len(sys.path))
            # We want WSFS to fail open so that commands that do not access WSFS can
            # still execute.
            try:
                import_hook = WsfsImportHook(path=sys_path, test_prefix=prefix)
                # Directly set the cache entry for the notebook dir as opposed to
                # modifying sys.path_hooks to minimize blast-radius of this change.
                sys.path_importer_cache[sys_path] = import_hook
            except Exception as e:
                print(
                    "Failed to update wsfs import hook for path {} with error {}".format(
                        prefix + notebook_dir, e
                    ),
                    file=sys.stderr,
                )

        # Clean up any workspace sys paths that may still exist from a previous
        # UDF that ran on the same worker process.
        # We do not remove any workspace sys paths that are set automatically
        # based on the notebook directory.
        for p in list(sys.path):
            if (
                p == prefix + "/Workspace" or p.startswith(prefix + "/Workspace/")
            ) and p not in notebook_workspace_sys_paths:
                sys.path.remove(p)

        # Add any workspace sys paths serialized in the current UDF to the end
        # of the current python process sys.path.
        # Any workspace sys paths that are set automatically based on the notebook
        # directory do not need to be added again.
        for p in workspace_sys_paths:
            path_with_prefix = prefix + p
            if path_with_prefix not in notebook_workspace_sys_paths:
                add_path(path_with_prefix, len(sys.path))
    else:
        # we don't know the notebook dir, maybe this is
        # not for a notebook, remove the placeholder
        remove_wsfs_path_placeholder()
    # END-EDGE

    # BEGIN-EDGE

    register_wsfs_path_finder()

    # END-EDGE


def setup_broadcasts(infile: IO) -> None:
    """
    Set up broadcasted variables.
    """
    if not is_remote_only():
        from pyspark.core.broadcast import Broadcast, _broadcastRegistry

    # fetch names and values of broadcast variables
    needs_broadcast_decryption_server = read_bool(infile)
    num_broadcast_variables = read_int(infile)
    if needs_broadcast_decryption_server:
        # read the decrypted data from a server in the jvm
        port = read_int(infile)
        auth_secret = utf8_deserializer.loads(infile)
        (broadcast_sock_file, _) = local_connect_and_auth(port, auth_secret)

    for _ in range(num_broadcast_variables):
        bid = read_long(infile)
        if bid >= 0:
            if needs_broadcast_decryption_server:
                read_bid = read_long(broadcast_sock_file)
                assert read_bid == bid
                _broadcastRegistry[bid] = Broadcast(sock_file=broadcast_sock_file)
            else:
                path = utf8_deserializer.loads(infile)
                _broadcastRegistry[bid] = Broadcast(path=path)

        else:
            bid = -bid - 1
            _broadcastRegistry.pop(bid)

    if needs_broadcast_decryption_server:
        broadcast_sock_file.write(b"1")
        broadcast_sock_file.close()


def send_accumulator_updates(outfile: IO) -> None:
    """
    Send the accumulator updates back to JVM.
    """
    write_int(len(_accumulatorRegistry), outfile)
    for aid, accum in _accumulatorRegistry.items():
        pickleSer._write_with_length((aid, accum._value), outfile)


# BEGIN-EDGE
def invalidate_caches():
    from types import MethodType
    from zipimport import zipimporter

    path_prefix_allowlist = [
        "/databricks/spark/python/lib/",
        "/databricks/jars/",
    ]
    origin = []
    try:
        # SC-126475: Patch zipimpoter to avoid refreshing the zipped packages expected
        # to don't change.
        for path, importer in sys.path_importer_cache.items():
            if isinstance(importer, zipimporter) and any(
                path.startswith(p) for p in path_prefix_allowlist
            ):

                def noop(self):
                    pass

                origin.append((importer, importer.invalidate_caches))
                importer.invalidate_caches = MethodType(noop, importer)

        importlib.invalidate_caches()
    finally:
        # Restore invalidate_caches.
        for importer, origin_func in origin:
            importer.invalidate_caches = origin_func


def monkey_patch_credential_chain_if_needed():
    """
    To enable service credentials in Isolated Lakeguard UDF, we patch the cloud SDKs, so that they retrieve
    credentials from Unity Catalog instead of their default implementation. This only works in Isolated Lakeguard
    UDFs.
    """
    if not os.getenv("SERVICE_CREDENTIAL_SOCKET_PATH"):
        # When this environment variable is not set, we are not running in an isolated environment.
        # This effectively disables the patching of the default credential chains in non-isolated environments.
        return
    try:
        from databricks.service_credentials.servicecredentials import (
            patch_default_credential_chains,
        )

        patch_default_credential_chains()
    except Exception as e:
        print(
            "Failed to patch default credential chains with error {}".format(e),
            file=sys.stderr,
        )


def remove_wsfs_path_placeholder():
    try:
        sys.path.remove("/WSFS_NOTEBOOK_DIR")
    except ValueError:
        pass


def change_cwd_to_notebook_dir(notebook_dir):
    # Change the current directory to the directory of the
    # notebook. Note that we are doing this after the jvm
    # makes the rpc call to workspace filesystem (wsfs) to
    # send the credential, otherwise changing directory
    # will fail in the wsfs fuse daemon to support local
    # tests to read files in a temp folder

    # We want WSFS to fail open so that commands that do not access WSFS can
    # still execute. If we fail to change to the WSFS dir then we are likely
    # missing the user token or WSFS has crashed, and future commands to access
    # WSFS files would fail anyways.
    try:
        os.chdir(notebook_dir)
    except Exception as e:
        print(
            "Failed to change to wsfs dir {} with error {}".format(notebook_dir, e),
            file=sys.stderr,
        )


# END-EDGE
