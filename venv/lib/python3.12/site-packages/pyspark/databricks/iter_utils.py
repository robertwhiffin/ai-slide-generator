#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2020-present Databricks, Inc.
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

import sys
import threading

if sys.version_info >= (3, 0):
    import queue as Queue
else:
    import Queue
from contextlib import contextmanager


class FetchThreadInterrupted(Exception):
    """
    An exception to be thrown when the iterator over the queue is interrupted before the FetchThread
    finishes to shutdown the FetchThread properly.
    """

    pass


class FetchThreadFinished(object):
    """
    A marker to notify the FetchThread finished.
    """

    pass


class FetchThreadError(object):
    """
    A marker to notify an exception was thrown by the FetchThread.
    """

    def __init__(self, exception):
        """
        Create a holder for an exception occured while fetching the iterator in FetchThread.

        :param exception: the exception to be held.
        """
        super(FetchThreadError, self).__init__()
        self.exception = exception


class FetchThread(threading.Thread):
    """
    An interruptable thread to prefetch the given iterator.
    """

    def __init__(self, iterator, queue, interrupt):
        """
        Create a thread to fetch from the given iterator and store the fetched items into the queue.

        :param iterator: an iterator to be fetched.
        :param queue: a queue to store the fetched items.
        :param interrupt: an event. If set, quit the thread and assume that queue won't be used.
        """
        super(FetchThread, self).__init__()
        self._iterator = iterator
        self._queue = queue
        self._interrupt = interrupt

    def _put_interruptable(self, item):
        """
        Put the given item into the queue.
        If the queue is full, try to put every 0.1 sec repeatedly until a free slot is available or
        the interupt event is set.

        :param item: the item to store into the queue.
        """
        done = False
        while not done:
            if self._interrupt.is_set():
                raise FetchThreadInterrupted()
            try:
                self._queue.put(item, block=True, timeout=0.1)
                done = True
            except Queue.Full:
                pass

    def _wait_interruptable_until_queue_is_available(self):
        """
        Make the thread wait until the queue is available.
        If the queue is full, check if a free slot is available or the interupt event is set every
        0.1 sec repeatedly.
        """
        while self._queue.full():
            if self._interrupt.is_set():
                raise FetchThreadInterrupted()
            try:
                with self._queue.not_full:
                    self._queue.not_full.wait(timeout=0.1)
            except Queue.Full:
                pass

    def run(self):
        try:
            for item in self._iterator:
                self._put_interruptable(item)
                self._wait_interruptable_until_queue_is_available()
            self._put_interruptable(FetchThreadFinished())
        except FetchThreadInterrupted:
            pass
        except BaseException as e:
            self._put_interruptable(FetchThreadError(e))


@contextmanager
def prefetch_iterator(iterator, max_prefetch):
    """
    Return an iterator to iterate over a queue, the items of which are prefetched from the given
    iterator in a separate thread.

    :param iterator: the iterator to be prefetched.
    :param max_prefetch: the capacity of the queue.
    """
    assert max_prefetch > 0, "The number of prefetch needs to be a positive integer"

    q = Queue.Queue(max_prefetch)
    interrupt = threading.Event()
    th = FetchThread(iterator, q, interrupt)
    th.start()

    def _prefetch_iter():
        while True:
            item = q.get()
            q.task_done()
            if isinstance(item, FetchThreadFinished):
                return
            elif isinstance(item, FetchThreadError):
                raise item.exception
            yield item

    try:
        yield _prefetch_iter()
    finally:
        interrupt.set()
        # Comment out here because this "join" is blocking. After we set the event, the thread
        # should definitely quit by itself.
        # th.join()
