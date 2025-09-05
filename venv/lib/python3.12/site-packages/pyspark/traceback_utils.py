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

from collections import namedtuple
import os
import traceback


CallSite = namedtuple("CallSite", "function file linenum")


def first_spark_call():
    """
    Return a CallSite representing the first Spark call in the current call stack.
    """
    tb = traceback.extract_stack()
    if len(tb) == 0:
        return None
    file, line, module, what = tb[len(tb) - 1]
    sparkpath = os.path.dirname(file)
    first_spark_frame = len(tb) - 1
    for i in range(0, len(tb)):
        file, line, fun, what = tb[i]
        if file.startswith(sparkpath):
            first_spark_frame = i
            break
    if first_spark_frame == 0:
        file, line, fun, what = tb[0]
        return CallSite(function=fun, file=file, linenum=line)
    sfile, sline, sfun, swhat = tb[first_spark_frame]
    ufile, uline, ufun, uwhat = tb[first_spark_frame - 1]
    return CallSite(function=sfun, file=ufile, linenum=uline)


class SCCallSiteSync:
    """
    Helper for setting the spark context call site.

    Example usage:
    from pyspark.core.context import SCCallSiteSync
    with SCCallSiteSync(<relevant SparkContext>) as css:
        <a Spark call>
    """

    _spark_stack_depth = 0

    def __init__(self, sc):
        call_site = first_spark_call()
        if call_site is not None:
            self._call_site = "%s at %s:%s" % (
                call_site.function,
                call_site.file,
                call_site.linenum,
            )
        else:
            self._call_site = "Error! Could not extract traceback info"
        self._context = sc

    def __enter__(self):
        if SCCallSiteSync._spark_stack_depth == 0:
            self._context._jsc.setCallSite(self._call_site)
        SCCallSiteSync._spark_stack_depth += 1

    def __exit__(self, type, value, tb):
        SCCallSiteSync._spark_stack_depth -= 1
        if SCCallSiteSync._spark_stack_depth == 0:
            self._context._jsc.setCallSite(None)


def format_worker_exception(exc_type, exc_value, tb):
    """
    Given information on an exception raised within a Pyspark worker, generates a formatted
    exception message and traceback with helpful debugging information surfaced higher in the
    message.

    :param exc_type: Type of the current exception, e.g. TypeError
    :param exc_value: Actual exception value, an instance of exc_type
    :param tb: Current exception traceback object
    :return: A string containing a reformatted exception message and traceback
    """
    raw_traceback = "".join(traceback.format_exception(exc_type, exc_value, tb))
    # Use the last line of the formatted exception to provide a summary of the actual error
    # (e.g. 'TypeError: cannot add str and int').
    # Per Python docs, format_exception_only usually returns a list containing a single line, but
    # for SyntaxErrors, there are multiple lines indicating the exact location of the SyntaxError.
    # In the SyntaxError case, it's fine for us to take the last line (e.g.
    # 'SyntaxError: unexpected EOF while parsing') to provide an initial summary of the error, as
    # we include the full traceback further below.
    # See https://docs.python.org/3/library/traceback.html#traceback.format_exception_only for
    # details
    exc_summary = traceback.format_exception_only(exc_type, exc_value)[-1].strip()
    exception_msg_header = ["'%s'" % exc_summary]
    # Add Databricks command info to exception message if available
    cmd_failure_frame = None
    for frame in traceback.extract_tb(tb):
        if "command" in frame.filename:
            cmd_failure_frame = frame
    if cmd_failure_frame is not None:
        exception_msg_header.append(
            ", from {cmd_filename}, line {cmd_lineno}".format(
                cmd_filename=cmd_failure_frame.filename, cmd_lineno=cmd_failure_frame.lineno
            )
        )
    return "{header}. Full traceback below:\n{full_traceback}".format(
        header="".join(exception_msg_header), full_traceback=raw_traceback
    )
