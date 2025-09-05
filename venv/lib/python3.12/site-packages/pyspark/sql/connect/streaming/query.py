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
from pyspark.sql.connect.utils import check_dependencies

check_dependencies(__name__)

import json
import sys
import warnings
from typing import TYPE_CHECKING, Any, cast, Dict, List, Optional, Union, Iterator, Iterable, Tuple
from threading import Thread, Lock

from pyspark.errors import StreamingQueryException, PySparkValueError
import pyspark.sql.connect.proto as pb2
from pyspark.sql.connect import proto
from pyspark.sql.streaming import StreamingQueryListener
from pyspark.sql.streaming.listener import (
    QueryStartedEvent,
    QueryProgressEvent,
    QueryIdleEvent,
    QueryTerminatedEvent,
    AsyncStateCommitCompletionEvent,
    StreamingQueryProgress,
)
from pyspark.sql.streaming.query import (
    StreamingQuery as PySparkStreamingQuery,
    StreamingQueryManager as PySparkStreamingQueryManager,
)
from pyspark.sql.utils import is_uds_channel
from pyspark.errors.exceptions.connect import (
    StreamingQueryException as CapturedStreamingQueryException,
)

if TYPE_CHECKING:
    from pyspark.sql.connect.session import SparkSession


class StreamingQuery:
    def __init__(
        self, session: "SparkSession", queryId: str, runId: str, name: Optional[str] = None
    ) -> None:
        self._session = session
        self._query_id = queryId
        self._run_id = runId
        self._name = name

    @property
    def id(self) -> str:
        return self._query_id

    id.__doc__ = PySparkStreamingQuery.id.__doc__

    @property
    def runId(self) -> str:
        return self._run_id

    runId.__doc__ = PySparkStreamingQuery.runId.__doc__

    @property
    def name(self) -> Optional[str]:
        return self._name

    name.__doc__ = PySparkStreamingQuery.name.__doc__

    @property
    def isActive(self) -> bool:
        return self._fetch_status().is_active

    isActive.__doc__ = PySparkStreamingQuery.isActive.__doc__

    def awaitTermination(self, timeout: Optional[int] = None) -> Optional[bool]:
        cmd = pb2.StreamingQueryCommand()
        if timeout is not None:
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                raise PySparkValueError(
                    errorClass="VALUE_NOT_POSITIVE",
                    messageParameters={"arg_name": "timeout", "arg_value": type(timeout).__name__},
                )
            cmd.await_termination.timeout_ms = int(timeout * 1000)
            terminated = self._execute_streaming_query_cmd(cmd).await_termination.terminated
            return terminated
        else:
            await_termination_cmd = pb2.StreamingQueryCommand.AwaitTerminationCommand()
            cmd.await_termination.CopyFrom(await_termination_cmd)
            self._execute_streaming_query_cmd(cmd)
            return None

    awaitTermination.__doc__ = PySparkStreamingQuery.awaitTermination.__doc__

    @property
    def status(self) -> Dict[str, Any]:
        proto = self._fetch_status()
        return {
            "message": proto.status_message,
            "isDataAvailable": proto.is_data_available,
            "isTriggerActive": proto.is_trigger_active,
        }

    status.__doc__ = PySparkStreamingQuery.status.__doc__

    @property
    def recentProgress(self) -> List[StreamingQueryProgress]:
        cmd = pb2.StreamingQueryCommand()
        cmd.recent_progress = True
        progress = self._execute_streaming_query_cmd(cmd).recent_progress.recent_progress_json
        return [StreamingQueryProgress.fromJson(json.loads(p)) for p in progress]

    recentProgress.__doc__ = PySparkStreamingQuery.recentProgress.__doc__

    @property
    def lastProgress(self) -> Optional[StreamingQueryProgress]:
        cmd = pb2.StreamingQueryCommand()
        cmd.last_progress = True
        progress = self._execute_streaming_query_cmd(cmd).recent_progress.recent_progress_json
        if len(progress) > 0:
            return StreamingQueryProgress.fromJson(json.loads(progress[-1]))
        else:
            return None

    lastProgress.__doc__ = PySparkStreamingQuery.lastProgress.__doc__

    def processAllAvailable(self) -> None:
        cmd = pb2.StreamingQueryCommand()
        cmd.process_all_available = True
        self._execute_streaming_query_cmd(cmd)

    processAllAvailable.__doc__ = PySparkStreamingQuery.processAllAvailable.__doc__

    def stop(self) -> None:
        cmd = pb2.StreamingQueryCommand()
        cmd.stop = True
        self._execute_streaming_query_cmd(cmd)

    stop.__doc__ = PySparkStreamingQuery.stop.__doc__

    def explain(self, extended: bool = False) -> None:
        cmd = pb2.StreamingQueryCommand()
        cmd.explain.extended = extended
        result = self._execute_streaming_query_cmd(cmd).explain.result
        print(result)

    explain.__doc__ = PySparkStreamingQuery.explain.__doc__

    def exception(self) -> Optional[StreamingQueryException]:
        cmd = pb2.StreamingQueryCommand()
        cmd.exception = True
        exception = self._execute_streaming_query_cmd(cmd).exception
        if not exception.HasField("exception_message"):
            return None
        else:
            # Drop the Java StreamingQueryException type info
            # exception_message maps to the return value of original
            # StreamingQueryException's toString method
            msg = exception.exception_message.split(": ", 1)[1]
            if exception.HasField("stack_trace"):
                msg += f"\n\nJVM stacktrace:\n{exception.stack_trace}"
            return CapturedStreamingQueryException(msg, reason=exception.error_class)

    exception.__doc__ = PySparkStreamingQuery.exception.__doc__

    def _fetch_status(self) -> pb2.StreamingQueryCommandResult.StatusResult:
        cmd = pb2.StreamingQueryCommand()
        cmd.status = True
        return self._execute_streaming_query_cmd(cmd).status

    def _execute_streaming_query_cmd(
        self, cmd: pb2.StreamingQueryCommand
    ) -> pb2.StreamingQueryCommandResult:
        cmd.query_id.id = self._query_id
        cmd.query_id.run_id = self._run_id
        exec_cmd = pb2.Command()
        exec_cmd.streaming_query_command.CopyFrom(cmd)
        (_, properties, _) = self._session.client.execute_command(exec_cmd)
        return cast(pb2.StreamingQueryCommandResult, properties["streaming_query_command_result"])


class StreamingQueryManager:
    def __init__(self, session: "SparkSession") -> None:
        self._session = session
        self._sqlb = StreamingQueryListenerBus(self)

    def close(self) -> None:
        self._sqlb.close()

    @property
    def active(self) -> List[StreamingQuery]:
        cmd = pb2.StreamingQueryManagerCommand()
        cmd.active = True
        queries = self._execute_streaming_query_manager_cmd(cmd).active.active_queries
        return [StreamingQuery(self._session, q.id.id, q.id.run_id, q.name) for q in queries]

    active.__doc__ = PySparkStreamingQueryManager.active.__doc__

    def get(self, id: str) -> Optional["StreamingQuery"]:
        cmd = pb2.StreamingQueryManagerCommand()
        cmd.get_query = id
        response = self._execute_streaming_query_manager_cmd(cmd)
        if response.HasField("query"):
            query = response.query
            return StreamingQuery(self._session, query.id.id, query.id.run_id, query.name)
        else:
            return None

    get.__doc__ = PySparkStreamingQueryManager.get.__doc__

    def awaitAnyTermination(self, timeout: Optional[int] = None) -> Optional[bool]:
        cmd = pb2.StreamingQueryManagerCommand()
        if timeout is not None:
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                raise PySparkValueError(
                    errorClass="VALUE_NOT_POSITIVE",
                    messageParameters={"arg_name": "timeout", "arg_value": type(timeout).__name__},
                )
            cmd.await_any_termination.timeout_ms = int(timeout * 1000)
            terminated = self._execute_streaming_query_manager_cmd(
                cmd
            ).await_any_termination.terminated
            return terminated
        else:
            await_any_termination_cmd = (
                pb2.StreamingQueryManagerCommand.AwaitAnyTerminationCommand()
            )
            cmd.await_any_termination.CopyFrom(await_any_termination_cmd)
            self._execute_streaming_query_manager_cmd(cmd)
            return None

    awaitAnyTermination.__doc__ = PySparkStreamingQueryManager.awaitAnyTermination.__doc__

    def resetTerminated(self) -> None:
        cmd = pb2.StreamingQueryManagerCommand()
        cmd.reset_terminated = True
        self._execute_streaming_query_manager_cmd(cmd)

    resetTerminated.__doc__ = PySparkStreamingQueryManager.resetTerminated.__doc__

    def addListener(self, listener: StreamingQueryListener) -> None:
        listener._set_spark_session(self._session)
        self._sqlb.append(listener)

    addListener.__doc__ = PySparkStreamingQueryManager.addListener.__doc__

    def removeListener(self, listener: StreamingQueryListener) -> None:
        self._sqlb.remove(listener)

    removeListener.__doc__ = PySparkStreamingQueryManager.removeListener.__doc__

    def _execute_streaming_query_manager_cmd(
        self, cmd: pb2.StreamingQueryManagerCommand
    ) -> pb2.StreamingQueryManagerCommandResult:
        exec_cmd = pb2.Command()
        exec_cmd.streaming_query_manager_command.CopyFrom(cmd)
        (_, properties, _) = self._session.client.execute_command(exec_cmd)
        return cast(
            pb2.StreamingQueryManagerCommandResult,
            properties["streaming_query_manager_command_result"],
        )


class StreamingQueryListenerBus:
    """
    A client side listener bus that is responsible for buffering client side listeners,
    receive listener events and invoke correct listener call backs.
    """

    def __init__(self, sqm: "StreamingQueryManager") -> None:
        self._sqm = sqm
        self._listener_bus: List[StreamingQueryListener] = []
        self._execution_thread: Optional[Thread] = None
        self._lock = Lock()

    def close(self) -> None:
        for listener in self._listener_bus:
            self.remove(listener)

    # BEGIN-EDGE
    def _request_credential(self) -> Iterable[Tuple[str, str]]:
        """
        Shared Cluster only. A call to request the server to cache the credentials of the caller
        and return a credential key. Subsequent call with this key would make the server
        handle the request with the cached credential.
        This is called under 2 conditions:
        1. For the initial request to the server to start a long-running gRPC response stream,
        This is because the long-running stream needs the credential to refresh the connection.
        Please see the comment near "_register_server_side_listener" method for details.
        2. For the subsequent listener callback function in case they contain spark command.
        This is to make sure such server connection is invoked with the registrant's credential.
        """
        assert is_uds_channel(self._sqm._session)
        cmd = pb2.StreamingQueryListenerBusCommand()
        cmd.cache_user_credentials = True
        exec_cmd = pb2.Command()
        exec_cmd.streaming_query_listener_bus_command.CopyFrom(cmd)
        (_, properties, _) = self._sqm._session.client.execute_command(exec_cmd)
        result = cast(
            pb2.StreamingQueryListenerEventsResult,
            properties["streaming_query_listener_events_result"],
        )
        return [("x-databricks-local-credentials-key", result.credential_key)]

    def _remove_cached_credential(self, listener: "StreamingQueryListener") -> None:
        """
        Shared Cluster only. A call to remove the credential cached.
        This is invoked when the listener is removed.
        """
        assert is_uds_channel(self._sqm._session)
        cmd = pb2.StreamingQueryListenerBusCommand()
        key = [
            meta[1]
            for meta in listener._get_metadata()
            if meta[0] == "x-databricks-local-credentials-key"
        ][0]
        cmd.remove_user_credentials = key
        exec_cmd = pb2.Command()
        exec_cmd.streaming_query_listener_bus_command.CopyFrom(cmd)
        self._sqm._session.client.execute_command(exec_cmd)

    # END-EDGE

    def append(self, listener: StreamingQueryListener) -> None:
        """
        Append a listener to the local listener bus. When the added listener is
        the first listener, request the server to create the server side listener
        and start a thread to handle query events.
        """
        # BEGIN-EDGE
        # In Shared Cluster, cache local credentials so that subsequent spark server call
        # from the listener callback functions won't throw
        if is_uds_channel(self._sqm._session):
            try:
                credentials_header = self._request_credential()
                listener._set_metadata(credentials_header)
            except Exception as e:
                warnings.warn(
                    f"In Shared Cluster, failed to add the listener credential "
                    f"because of exception: {e}.\n The listener is not added. Please try again. "
                    f"If this error persists, please contact support."
                )
                return
        # This runs on the main thread, so this client is the registrant's client
        listener._set_client(self._sqm._session.client)
        # END-EDGE
        with self._lock:
            self._listener_bus.append(listener)

            if len(self._listener_bus) == 1:
                assert self._execution_thread is None
                try:
                    result_iter = self._register_server_side_listener()
                except Exception as e:
                    warnings.warn(
                        f"Failed to add the listener because of exception: {e}\n"
                        f"The listener is not added, please add it again."
                    )
                    self._listener_bus.remove(listener)
                    return
                self._execution_thread = Thread(
                    target=self._query_event_handler,
                    args=(result_iter,),
                )
                self._execution_thread.start()

    def remove(self, listener: StreamingQueryListener) -> None:
        """
        Remove the listener from the local listener bus.

        When the listener is not presented in the listener bus, do nothing.

        When the removed listener is the last listener, ask the server to remove
        the server side listener.
        As a result, the listener handling thread created before
        will return after processing remaining listener events. This function blocks until
        all events are processed.
        """
        with self._lock:
            if listener not in self._listener_bus:
                return

            if len(self._listener_bus) == 1:
                cmd = pb2.StreamingQueryListenerBusCommand()
                cmd.remove_listener_bus_listener = True
                exec_cmd = pb2.Command()
                exec_cmd.streaming_query_listener_bus_command.CopyFrom(cmd)
                try:
                    self._sqm._session.client.execute_command(exec_cmd)
                except Exception as e:
                    warnings.warn(
                        f"Failed to remove the listener because of exception: {e}\n"
                        f"The listener is not removed, please remove it again."
                    )
                    return
                if self._execution_thread is not None:
                    self._execution_thread.join()
                    self._execution_thread = None

            self._listener_bus.remove(listener)
            # BEGIN-EDGE
            if is_uds_channel(self._sqm._session):
                try:
                    self._remove_cached_credential(listener)
                except Exception as e:
                    warnings.warn(
                        f"In Shared Cluster, failed to remove the listener credential "
                        f"because of exception: {e}.\n The listener is still removed."
                    )
            # END-EDGE

    def _register_server_side_listener(self) -> Iterator[Dict[str, Any]]:
        """
        Send add listener request to the server, after received confirmation from the server,
        start a new thread to handle these events.
        """
        # BEGIN-EDGE
        credential_metadata = []
        # In Shared Clusters, the credential is only valid during the notebook cell's lifetime.
        # The result_iter, a ExecutePlanResponseReattachableIterator, would lose its credentials
        # when reattch happens. So here we make a call to request credential and store it
        # in the iterator instance.
        # The credential is requested on behalf of the default user before
        # any user runs any command. It is purely used for connection refresh,
        # so it should not have any UC related permissions.
        if is_uds_channel(self._sqm._session):
            credential_metadata = self._request_credential()
        # END-EDGE
        cmd = pb2.StreamingQueryListenerBusCommand()
        cmd.add_listener_bus_listener = True
        exec_cmd = pb2.Command()
        exec_cmd.streaming_query_listener_bus_command.CopyFrom(cmd)
        result_iter = self._sqm._session.client.execute_command_as_iterator(
            command=exec_cmd, extra_request_metadata=credential_metadata  # EDGE
        )
        # Main thread should block until received listener_added_success message
        for result in result_iter:
            response = cast(
                pb2.StreamingQueryListenerEventsResult,
                result["streaming_query_listener_events_result"],
            )
            if response.HasField("listener_bus_listener_added"):
                break
        return result_iter

    def _query_event_handler(self, iter: Iterator[Dict[str, Any]]) -> None:
        """
        Handler function passed to the new thread, if there is any error while receiving
        listener events, it means the connection is unstable. In this case, remove all listeners
        and tell the user to add back the listeners.
        """
        try:
            for result in iter:
                response = cast(
                    pb2.StreamingQueryListenerEventsResult,
                    result["streaming_query_listener_events_result"],
                )
                for event in response.events:
                    deserialized_event = self.deserialize(event)
                    self.post_to_all(deserialized_event)

        except Exception as e:
            warnings.warn(
                "StreamingQueryListenerBus Handler thread received exception, all client side "
                f"listeners are removed and handler thread is terminated. The error is: {e}"
            )
            with self._lock:
                self._execution_thread = None
                self._listener_bus.clear()
            return

    @staticmethod
    def deserialize(
        event: str,
    ) -> Union[
        "QueryProgressEvent",
        "QueryIdleEvent",
        "QueryTerminatedEvent",
        "AsyncStateCommitCompletionEvent",
    ]:
        if event.event_type == proto.StreamingQueryEventType.QUERY_PROGRESS_EVENT:
            return QueryProgressEvent.fromJson(json.loads(event.event_json))
        elif event.event_type == proto.StreamingQueryEventType.QUERY_TERMINATED_EVENT:
            return QueryTerminatedEvent.fromJson(json.loads(event.event_json))
        elif event.event_type == proto.StreamingQueryEventType.QUERY_IDLE_EVENT:
            return QueryIdleEvent.fromJson(json.loads(event.event_json))
        # BEGIN-EDGE
        elif event.event_type == proto.StreamingQueryEventType.ASYNC_STATE_COMMIT_COMPLETION_EVENT:
            return AsyncStateCommitCompletionEvent.fromJson(json.loads(event.event_json))
        # END-EDGE
        else:
            raise PySparkValueError(
                errorClass="UNKNOWN_VALUE_FOR",
                messageParameters={"var": f"proto.StreamingQueryEventType: {event.event_type}"},
            )

    def post_to_all(
        self,
        event: Union[
            "QueryStartedEvent",
            "QueryProgressEvent",
            "QueryIdleEvent",
            "QueryTerminatedEvent",
            "AsyncStateCommitCompletionEvent",
        ],
    ) -> None:
        """
        Post listener events to all active listeners, note that if one listener throws,
        it should not affect other listeners.
        """
        with self._lock:
            for listener in self._listener_bus:
                with ClientContext(
                    self._sqm._session, listener._client, listener._get_metadata()
                ):  # EDGE
                    try:
                        if isinstance(event, QueryStartedEvent):
                            listener.onQueryStarted(event)
                        elif isinstance(event, QueryProgressEvent):
                            listener.onQueryProgress(event)
                        elif isinstance(event, QueryIdleEvent):
                            listener.onQueryIdle(event)
                        elif isinstance(event, QueryTerminatedEvent):
                            listener.onQueryTerminated(event)
                        # BEGIN-EDGE
                        elif isinstance(event, AsyncStateCommitCompletionEvent):
                            listener.onAsyncStateCommitCompletion(event)
                        # END-EDGE
                        else:
                            warnings.warn(f"Unknown StreamingQueryListener event: {event}")
                    except Exception as e:
                        warnings.warn(f"Listener {str(listener)} threw an exception\n{e}")


# BEGIN-EDGE
class ClientContext:
    """
    DBR only context manager for swapping essential credentials when listeners' callback is called.
    This should only be invoked on the listener's handling thread.
    Under this context, connection to server will use any connect to the server would use
    the credentials of "client", with additional credentials defined in "param".
    Switching context between listeners ensures each listener's callback is invoked using
    the registrant's credential.
    Possible credential misuse issue caused by concurrent invocation of user command and listener
    callback function is avoided by making "client" property of SparkSession a thread local.
    """

    def __init__(self, spark, client, params: Iterable[Tuple[str, str]]):
        self.spark = spark
        self.client = client
        self.params = params

    def __enter__(self):
        self.prev_client = self.spark.thread_local.client
        self.prev_extra_request_metadata = getattr(
            self.spark.thread_local.client.thread_local, "extra_request_metadata", []
        )
        self.spark.thread_local.client = self.client
        self.spark.thread_local.client.thread_local.extra_request_metadata = self.params

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.spark.thread_local.client.thread_local.extra_request_metadata = (
            self.prev_extra_request_metadata
        )
        self.spark.thread_local.client = self.prev_client


# END-EDGE


def _test() -> None:
    import doctest
    import os
    from pyspark.sql import SparkSession as PySparkSession
    import pyspark.sql.connect.streaming.query

    os.chdir(os.environ["SPARK_HOME"])

    globs = pyspark.sql.connect.streaming.query.__dict__.copy()

    globs["spark"] = (
        PySparkSession.builder.appName("sql.connect.streaming.query tests")
        .remote(os.environ.get("SPARK_CONNECT_TESTING_REMOTE", "local[4]"))
        .getOrCreate()
    )

    # Setup Scope for UC Testing.
    from pyspark.testing.connectutils import ReusedConnectTestCase

    ReusedConnectTestCase.update_client_for_uc(globs["spark"])

    (failure_count, test_count) = doctest.testmod(
        pyspark.sql.connect.streaming.query,
        globs=globs,
        optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE | doctest.REPORT_NDIFF,
    )
    globs["spark"].stop()

    if failure_count:
        sys.exit(-1)


if __name__ == "__main__":
    _test()
