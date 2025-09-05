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

import numbers
import os
import socket
import sys
import textwrap
import traceback

from threading import Thread, Lock, Event
from importlib import import_module

from pyspark.databricks.utils.memory import clear_memory, get_used_memory

worker_main_is_running = False
worker_main_is_running_lock = Lock()


def run_worker_main(conn, addr, worker_main, extended_lifetime):
    global worker_main_is_running, worker_main_is_running_lock
    """
    Runs the worker_main function in a separate thread. This is necessary because the
    SafeSpark api server makes connection attempts to check liveliness of the worker,
    however disconnects immediately. This function will only allow one connection to
    proceed past the initial connection attempt.
    """

    # Wait for some initial bytes to be sent, so we don't start worker_main if it's just
    # a connection attempt.
    if not conn.recv(4, socket.MSG_PEEK):
        # We do not log here, as liveness checks would only clutter the logs.
        conn.close()
        return

    with worker_main_is_running_lock:
        # Beyond simple connection attempts, only one connection should proceed past this point.
        if worker_main_is_running:
            print("worker_main is already running, this is unexpected.")
            sys.exit(os.EX_SOFTWARE)
        worker_main_is_running = True
    print(f"Received bytes, handing over to worker ({conn} {addr})")

    conn.settimeout(None)  # disable timeout, as worker_main does not expect this to be set

    # The following code is very similar to PySpark's daemon.py - we keep running worker_main
    # until we get a non-zero exit code, or SPARK_REUSE_WORKER is not set.
    reuse = os.environ.get("SPARK_REUSE_WORKER", "0") == "1"
    buffer_size = int(os.environ.get("SPARK_BUFFER_SIZE", 65536))

    # Here comes specific parameters to control connection between proxy and workerwrap.
    # As it is spark internal config, we consider it safe to transform to int without exception handling.
    tcp_so_write_timeo = int(os.environ.get("SPARK_WRAP_SO_SNDTIMEO", "-1"))
    if tcp_so_write_timeo > 0:
        print("setting SO_SNDTIMEO to ", tcp_so_write_timeo)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack('ll', tcp_so_write_timeo, 0))
    tcp_user_timeout = int(os.environ.get("SPARK_WRAP_TCP_USER_TIMEOUT", "-1"))
    if tcp_user_timeout > 0:
        print("setting TCP_USER_TIMEOUT to ", tcp_user_timeout)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, tcp_user_timeout)

    infile = os.fdopen(os.dup(conn.fileno()), "rb", buffer_size)
    outfile = os.fdopen(os.dup(conn.fileno()), "wb", buffer_size)

    exit_code = 0
    while True:
        try:
            worker_main(infile, outfile)
        except SystemExit as exc:
            print("Exception caught in worker_main:")
            traceback.print_exc()
            if isinstance(exc.code, numbers.Integral):
                exit_code = exc.code
            else:
                exit_code = 1
        finally:
            try:
                outfile.flush()
            except Exception:
                pass
        if reuse and exit_code == 0:
            # To avoid excessive memory usage we clear up memory after each run.
            mem_before = get_used_memory()
            clear_memory()
            mem_after = get_used_memory()
            print(f"worker_main finished with rc=0, reusing worker ({mem_before}->{mem_after})")
            continue
        else:
            print(f"worker_main finished with {exit_code}")
            break

    if extended_lifetime:
        sys.stdout.flush()
        sys.stderr.flush()
        print("Worker is done, waiting to be killed from the outside.", file=sys.stderr)
        Event().wait()
    else:
        conn.close()
        print("run_worker_main finished", file=sys.stderr)
        # When we reach this point, no reuse of the worker is expected by PySpark -
        # we can safely stop the whole process & container.
        sys.exit(0)


def main(port: int, worker_main, extended_lifetime):
    """
    Wait for connections - the API server makes connection attempts to
    check liveliness of the worker, however disconnects immediately.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("0.0.0.0", port))
    s.listen()
    while True:
        conn, addr = s.accept()
        conn.settimeout(30)  # expect some initial bytes to be sent quickly
        Thread(target=run_worker_main, args=(conn, addr, worker_main, extended_lifetime)).start()

def load_worker_main_from_command_args(args):
    """
    Loads the worker main from the command line arguments.
    Returns the worker module and the port.
    """
    if len(args) != 3:
        print("Usage: -m pyspark.databricks.workerwrap <worker_module> <port>")
        sys.exit(os.EX_USAGE)

    _, worker_module, port_arg = args
    imported_module = import_module(worker_module)
    worker_main = getattr(imported_module, "main")

    port = int(port_arg.split(":")[-1])
    return (port, worker_main)

if __name__ == "__main__":
    port, worker_main = load_worker_main_from_command_args(sys.argv)

    startup_info = f"""\
       port: {port}
       sys.argv: {sys.argv}
       sys.version_info: {sys.version_info}
       sys.executable: {sys.executable}
       sys.path: {sys.path}
       os.environ: {dict(os.environ)}
       uid: {os.getuid()}
       groups: {os.getgroups()}"""
    print(textwrap.dedent(startup_info))
    extended_lifetime = os.environ.pop("PYTHON_ISOLATION_EXTENDED_LIFETIME", "false") == "true"

    main(port, worker_main, extended_lifetime)
