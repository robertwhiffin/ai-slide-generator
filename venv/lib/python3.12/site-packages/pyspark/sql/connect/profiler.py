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
import ast  # EDGE
import linecache  # EDGE
import hashlib  # EDGE
import textwrap  # EDGE
import traceback  # EDGE

from typing import List, Optional, TYPE_CHECKING, Tuple

from pyspark.sql.profiler import ProfilerCollector, ProfileResultsParam
import pyspark.sql.connect.proto as pb2

if TYPE_CHECKING:
    from pyspark.sql._typing import ProfileResults


class ConnectProfilerCollector(ProfilerCollector):
    """
    ProfilerCollector for Spark Connect.
    """

    def __init__(self) -> None:
        super().__init__()
        self._value = ProfileResultsParam.zero(None)

    @property
    def _profile_results(self) -> "ProfileResults":
        with self._lock:
            return self._value if self._value is not None else {}

    def _update(self, update: "ProfileResults") -> None:
        with self._lock:
            self._value = ProfileResultsParam.addInPlace(self._profile_results, update)


# BEGIN-EDGE

# Global cache, mapping sha(256) of code to its parsed AST, to avoid re-parsing
# the common case where multiple calls are made from the same file.
_ast_cache = (None, None)


def _get_start_end(node: ast.AST) -> Optional[Tuple[int, int]]:
    """
    Returns the (start, end) of the AST node, or None if the fields are not set.
    """
    if hasattr(node, "lineno"):
        end_lineno = getattr(node, "end_lineno", node.lineno)
        return (node.lineno, end_lineno)
    return None


def _node_encloses_line(node: ast.AST, line_number: int) -> bool:
    """
    Returns True if the node has a (start, end) and the provided line_number
    is somewhere in between.
    """
    start_end = _get_start_end(node)
    if start_end is not None:
        return start_end[0] <= line_number <= start_end[1]
    return False


def _find_context_lines(code: str, line_number: int):
    """
    Given code as a string and a line number (1-indexed) into that code,
    this method will try to find the *statement* that encloses that line.
    All the lines (the "context") pertaining to this statement will be returned.
    If this process fails, returns None.
    """

    class LineFinder(ast.NodeVisitor):
        def __init__(self):
            self.result: Optional[Tuple[int, int]] = None

        def visit(self, node: ast.AST):
            if hasattr(node, "body") and isinstance(node.body, list):
                for child in node.body:
                    if _node_encloses_line(child, line_number):
                        self.visit(child)
                    if self.result:
                        return
            elif _node_encloses_line(node, line_number):
                self.result = _get_start_end(node)
                return  # Stop visiting further nodes
            super().visit(node)

    # Compute code's hash to see if it matches the last time.
    global _ast_cache
    (last_hash, last_ast) = _ast_cache

    hash_object = hashlib.sha256()
    hash_object.update(code.encode())
    cur_hash = hash_object.hexdigest()

    try:
        tree = None
        if last_hash == cur_hash:
            tree = last_ast
        else:
            tree = ast.parse(code)
            _ast_cache = (cur_hash, tree)
        finder = LineFinder()
        finder.visit(tree)
    except SyntaxError:
        return None

    if finder.result:
        start, end = finder.result
        code_lines = code.splitlines()
        return "\n".join(code_lines[start - 1 : end])
    return None


# Looks up the stack of the caller to find the user code which submitted it.
# 'context_exclusions' are filenames that will be excluded from the search, to avoid
# returning system code. Partial string matches.
# 'max_statement_len' refers to the maximum amount of code from the context that will
# be returned, in case the identified line is super long.
def detect_client_context(
    context_exclusions: List[str], max_statement_len: int = 1024
) -> pb2.ClientCallContext:
    stack_trace = traceback.extract_stack()
    # find highest frame in stack trace that does not belong to the pyspark or dbruntime package
    stack_trace.reverse()
    frame = None
    for f in stack_trace:
        if not any(p in f.filename for p in context_exclusions):
            frame = f
            break
    if frame is not None:
        source_code = "".join(linecache.getlines(frame.filename))

        # Try to collect the full context statement.
        context_lines = _find_context_lines(source_code, frame.lineno)

        # Fall back to using the stack frame's line if that failed.
        if context_lines is None:
            context_lines = frame.line

        # Drop any indentation from nesting of our found code.
        context_lines = textwrap.dedent(context_lines)

        return pb2.ClientCallContext(
            file_name=frame.filename.split("/")[-1],
            line_no=frame.lineno,
            statement=context_lines[:max_statement_len],
        )
    return


# END-EDGE
