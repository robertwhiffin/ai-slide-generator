#!/databricks/python/bin/python

#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2019 Databricks, Inc.
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

"""
# This script will run the provided executable in $2 as the user whose ID is $1. The new process
# will inherit the environment of the launching process.

# Usage: wrapped_python.py PYTHON_UID PYTHON_EXECUTABLE_PATH OTHER_PYTHON_ARGS
# Example: wrapped_python.py 1000 /databricks/python/bin/python -u /tmp/1504138606774/PythonShell.py
"""

import os
import subprocess
import sys
import time

SPARK_USER_GROUP = "spark-users"


# We throw an error if the group does not exist. We currently only call this on the spark-users
# group (above), which we create during container setup.
def get_gid_for_groupname(groupname):
    try:
        group_entry = subprocess.check_output(["getent", "group", groupname]).decode("utf-8")
    except subprocess.CalledProcessError as e:
        # returncode = 2 --> no such group
        if e.returncode == 2:
            raise RuntimeError("Attempted to get gid for nonexistent group: '%s'" % groupname)
        else:
            raise e
    return int(group_entry.split(":")[2].strip())


def get_uid_for_username(username):
    uid_str = subprocess.check_output(["id", "-u", username]).decode("utf-8")
    return int(uid_str.strip())


def set_process_identity(uid, user_gid, spark_users_gid):
    """
    Performs all necessary steps to de-escalate this process's privilege from that of the root user
    to that of the process-specific low-privilege user.

    :param uid: The process-specific low-privilege users's ID
    :param user_gid: The ID of the process-specific low-privilege users's group
    :param spark_users_gid: The ID of the spark-users group
    """

    # SC-14300: If we don't explicitly set the list of groups, we will keep our initial set of
    # supplementary groups, which includes the root group.
    # We set the process to belong to both the user-specific group and the general spark-users group
    # so that it can read files that must be accessible to all Spark user processes.
    os.setgroups([user_gid, spark_users_gid])

    # We also need to call setgid() to change the process's primary group. This is the group that
    # will be the group owner of all new files created by the process, so we use the user-specific
    # group here. If we used the spark-users group as our primary group, it would be possible for
    # other members of the spark-users group to read files we created (as long as those files had
    # the group read bit set).
    os.setgid(int(user_gid))

    # Setting the uid must be the last syscall we make, since once we change our uid we no
    # longer have permission to make syscalls
    os.setuid(int(uid))


def do_all_setup_for_username(username):
    import pwd  # Do this lazily since it's available on Linux only

    # Only do this setup if we would actually change our user. This check allows us to run this code
    # as a non-root user.
    if username != pwd.getpwuid(os.getuid()).pw_name:
        # Must make sure that Spark user group exists before creating user
        spark_users_gid = get_gid_for_groupname(SPARK_USER_GROUP)
        uid = get_uid_for_username(username)
        user_gid = get_gid_for_groupname(username)
        if (
            os.environ.get("ENABLE_IPTABLES", "false") == "true"
            and "PYSPARK_GATEWAY_PORT" in os.environ
        ):
            # Prepend a rule to the iptables chain in order to allow the user to connect
            # from the Python process back to the driver JVM. This code is only run on
            # the driver (PYSPARK_GATEWAY_PORT will not be defined on executors).
            gateway_port = int(os.environ["PYSPARK_GATEWAY_PORT"])
            iptables_start_time = time.time()
            subprocess.check_call(
                [
                    "iptables",
                    "-I",
                    "OUTPUT",
                    "-m",
                    "owner",
                    "--uid-owner",
                    str(uid),
                    "-d",
                    "127.0.0.1",
                    "-p",
                    "tcp",
                    "--destination-port",
                    str(gateway_port),
                    "-j",
                    "ACCEPT",
                    # [ES-609068] Wait for 60 seconds for the case of lock contention.
                    "-w",
                    "60",
                ]
            )
            print(
                "do_all_setup_for_username: iptables command took %s seconds"
                % (time.time() - iptables_start_time)
            )
        set_process_identity_start_time = time.time()
        set_process_identity(uid, user_gid, spark_users_gid)
        print(
            "do_all_setup_for_username: set_process_identity took %s seconds"
            % (time.time() - set_process_identity_start_time)
        )


if __name__ == "__main__":
    do_all_setup_for_username(sys.argv[1])
    program = sys.argv[2]
    args = sys.argv[2:]
    os.execvp(program, args)
