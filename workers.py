"""
Worker Classes for Z39.50 Server Queries.

This module defines worker classes that handle querying Z39.50 servers in separate threads,
allowing the main application to perform network operations without blocking the user interface.
It leverages PyQt5's threading capabilities to manage concurrent searches, process server
responses, and emit signals for progress updates and result handling.

Key Components:
    - QueryType (Enum):
        An enumeration defining the types of queries supported, such as ISBN-based or Title &
        Author-based searches.

    - BaseWorker (QObject):
        An abstract base class providing common functionality for worker classes, including query
        construction,
        cancellation handling, and signal definitions for inter-thread communication.

    - ServerQueryRunnable (QRunnable):
        A runnable class that performs the actual querying of a single Z39.50 server. It
        processes the server's
        response, handles malformed data, and emits results or error messages back to the main
        thread.

    - Worker (BaseWorker):
        A concrete worker class that manages the lifecycle of multiple server queries. It
        utilizes a QThreadPool
        to execute `ServerQueryRunnable` instances concurrently, tracks progress, and aggregates
        results.

Key Signals:
    - progress (int):
        Emitted to indicate the progress percentage of the ongoing search operation.

    - result_found (dict):
        Emitted when a valid search result is found, containing summary information and raw data.

    - error (str):
        Emitted when an error occurs during the search process, providing an error message.

    - finished (signal):
        Emitted when the worker has completed all search operations, regardless of success or
        cancellation.

Features:
    - Concurrent querying of multiple Z39.50 servers using a thread pool.
    - Graceful handling and logging of malformed MARC data and server response issues.
    - Cancellation of ongoing search operations upon user request.
    - Progress tracking and real-time updates to the main application.

Usage:
    Instantiate the `Worker` class with the necessary parameters and connect its signals to
    appropriate
    slots or handler functions within the main application.

Example:
    ```python
    from workers import Worker, QueryType

    def handle_result(result):
        print(f"Result from {result['summary']}: {result['number_of_hits']} hits")

    def handle_progress(value):
        print(f"Progress: {value}%")

    worker = Worker(
        servers=server_list,
        query_type=QueryType.ISBN,
        query="978-3-16-148410-0",
        start=1,
        timeout=10,
        max_threads=10
    )
    worker.result_found.connect(handle_result)
    worker.progress.connect(handle_progress)
    worker.finished.connect(lambda: print("Search completed."))
    ```

Dependencies:
    - PyQt5
    - pymarc
    - subprocess
    - typing
    - enum
    - dataclasses
    - re
    - List, Dict, Union, Tuple from typing
"""

import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Union, List, Dict, Tuple, Optional

from PyQt5.QtCore import (
    QObject, pyqtSignal, QRunnable, pyqtSlot, QMutexLocker, QMutex, QThreadPool,
    )
from pymarc import Record

from utils import clean_yaz_output, extract_marc_record


class QueryType(Enum):
    """Enumeration for query types."""
    ISBN = "isbn"
    TITLE_AUTHOR = "title_author"


@dataclass
class WorkerConfig:
    """
    Configuration settings for the Worker.

    Attributes:
        servers (List[Dict]): List of server configurations.
        query_type (QueryType): Type of the query to perform.
        query (Union[str, Tuple[str, str]]): The search query, either a single string or a tuple
        of strings.
        start (int, optional): Starting record number. Defaults to 1.
        timeout (int, optional): Timeout for subprocess operations in seconds. Defaults to 10.
        max_threads (int, optional): Maximum number of concurrent threads. Defaults to 50.
    """
    servers: List[Dict]
    query_type: QueryType
    query: Union[str, Tuple[str, str]]
    start: int = 1
    timeout: int = 10
    max_threads: int = 50


@dataclass
class NextRecordWorkerConfig:
    """
    Configuration settings for the NextRecordWorker.

    Attributes:
        server_info (Dict): Information about the server.
        query_type (QueryType): Type of the query.
        query (Union[str, Tuple[str, str]]): The search query.
        start (int): Starting record number.
        timeout (int): Timeout for the subprocess.
    """
    server_info: Dict
    query_type: QueryType
    query: Union[str, Tuple[str, str]]
    start: int
    timeout: int


class BaseWorker(QObject):
    """Base worker class with common functionality for querying servers."""

    finished = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(
            self, query_type: QueryType, query: Union[str, Tuple[str, str]], start: int,
            timeout: int
            ):
        """
        Initialize the BaseWorker.

        Args:
            query_type (QueryType): Type of the query.
            query (str or tuple): The search query.
            start (int): Starting record number.
            timeout (int): Timeout for the subprocess.
        """
        super().__init__()
        self.query_type = query_type
        self.query = query
        self.start = start
        self.timeout = timeout
        self._cancel_requested = False

    def build_search_command(self) -> str:
        """
        Build the search command based on the query type.

        Returns:
            str: The search command string.
        """
        if self.query_type == QueryType.ISBN:
            search_command = f'find @attr 1=7 @attr 4=1 "{self.query}"\n'
        elif self.query_type == QueryType.TITLE_AUTHOR:
            title, author = self.query
            search_command = (f'find @and @attr 1=4 @attr 4=1 "{title}" '
                              f'@attr 1=1003 @attr 4=1 "{author}"\n')
        else:
            search_command = ""
        return search_command

    def cancel(self):
        """Cancel the worker operation."""
        self._cancel_requested = True

    @property
    def cancel_requested(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancel_requested


class ServerQueryRunnable(QRunnable):
    """Runnable class for querying a server in a separate thread."""

    def __init__(self, worker: 'Worker', server: dict):
        """
        Initialize the ServerQueryRunnable.

        Args:
            worker (Worker): The parent worker instance.
            server (dict): Server information.
        """
        super().__init__()
        self.worker = worker
        self.server = server

    @pyqtSlot()
    def run(self):
        """Execute the server query."""
        if self.worker.cancel_requested:
            return

        server_name = self.server.get("name", "Unknown Server")
        command = self._prepare_command(server_name)
        if not command:
            return

        cmd, full_command = command

        try:
            with subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW, ) as process:
                with QMutexLocker(self.worker.mutex):
                    self.worker.processes.append(process)

                try:
                    stdout, _ = process.communicate(input=full_command, timeout=self.worker.timeout)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    self.worker.log_message.emit(f"Timeout querying {server_name}.")
                    return

                if self.worker.cancel_requested:
                    process.terminate()
                    return

                if process.returncode == 0 and stdout.strip():
                    cleaned_data = clean_yaz_output(stdout)
                    number_of_hits = self._extract_hits(stdout)
                    if number_of_hits > 0:
                        self._emit_result(cleaned_data, number_of_hits, server_name)
                    else:
                        self.worker.log_message.emit(f"No records found in {server_name}.")
                else:
                    self.worker.log_message.emit(f"No records found in {server_name}.")

        except (subprocess.CalledProcessError, OSError) as e:
            if not self.worker.cancel_requested:
                self.worker.log_message.emit(f"Error querying {server_name}: {e}")
        finally:
            with QMutexLocker(self.worker.mutex):
                # Remove the process if it's still in the list
                self.worker.processes = [p for p in self.worker.processes if p.poll() is None]

            # Update progress
            with QMutexLocker(self.worker.mutex):
                self.worker.completed_servers += 1
                progress = int((self.worker.completed_servers / len(self.worker.servers)) * 100)
            self.worker.progress.emit(progress)

    def _prepare_command(self, server_name: str) -> Optional[Tuple[List[str], str]]:
        """Prepare the command to execute."""
        try:
            cmd = ["yaz-client",
                   f'{self.server["host"]}:{self.server["port"]}/{self.server["database"]}', ]
            search_command = self.worker.build_search_command()
            show_command = f"show {self.worker.start}\n"
            full_command = search_command + show_command

            command_for_logging = full_command.replace("\n", " ")
            self.worker.log_message.emit(
                f"Connecting to {server_name}: {' '.join(cmd)} with {command_for_logging}"
                )
            return cmd, full_command
        except KeyError as e:
            self.worker.log_message.emit(f"Missing server key {e} in {server_name}.")
            return None

    def _extract_hits(self, stdout: str) -> int:
        """Extract the number of hits from the output."""
        hits_line = next(
            (line for line in stdout.splitlines() if "Number of hits:" in line), None
            )
        if hits_line:
            try:
                number_of_hits_str = hits_line.split(":")[1].split(",")[0].strip()
                return int(number_of_hits_str)
            except (IndexError, ValueError):
                self.worker.log_message.emit(
                    f"Unable to parse number of hits from line: '{hits_line}'"
                    )
        return 0

    def _emit_result(self, cleaned_data: str, number_of_hits: int, server_name: str):
        """Emit the search result."""
        result = {
            "summary": f"{server_name} ({self.server['host']}:{self.server['port']}/"
                       f"{self.server['database']})", "raw_data": cleaned_data,
            "number_of_hits": number_of_hits,
            }
        self.worker.result_found.emit(result)


class Worker(BaseWorker):
    """Worker class for handling Z39.50 searches in a separate thread."""

    progress = pyqtSignal(int)
    result_found = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, config: WorkerConfig):
        """
        Initialize the Worker.

        Args:
            config (WorkerConfig): Configuration for the worker.
        """
        super().__init__(config.query_type, config.query, config.start, config.timeout)
        self.servers = config.servers
        self.processes = []
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(config.max_threads)
        self.mutex = QMutex()
        self.completed_servers = 0

    def run(self):
        """Execute the Z39.50 searches in a separate thread."""
        try:
            total_servers = len(self.servers)
            if total_servers == 0:
                self.finished.emit()
                return
            self.log_message.emit(f"Total servers to query: {total_servers}")

            for server in self.servers:
                if self.cancel_requested:
                    break
                runnable = ServerQueryRunnable(self, server)
                self.threadpool.start(runnable)

            self.threadpool.waitForDone()
            if not self.cancel_requested:
                self.progress.emit(100)
        except (subprocess.CalledProcessError, OSError) as e:
            self.log_message.emit(f"Handled exception in worker thread: {e}")
            self.error.emit(f"Worker encountered an exception: {e}")
        finally:
            self._cleanup_processes()  # Ensure cleanup
            self.finished.emit()

    def _cleanup_processes(self):
        """Clean up subprocesses."""
        with QMutexLocker(self.mutex):
            for process in self.processes:
                if process.poll() is None:  # Process is still running
                    self.terminate_process(process)
            self.processes.clear()

    def terminate_process(self, process: subprocess.Popen):
        """Attempt to terminate a subprocess and handle exceptions."""
        try:
            process.terminate()
            try:
                process.wait(timeout=5)  # Optional: Wait for the process to terminate
            except subprocess.TimeoutExpired:
                self.log_message.emit(f"Process {process.pid} did not terminate in time.")
        except OSError as e:
            self.log_message.emit(f"OSError terminating process {process.pid}: {e}")
        except AttributeError as e:
            self.log_message.emit(f"AttributeError terminating process {process.pid}: {e}")

    def cancel(self):
        """Cancel the worker operation."""
        super().cancel()
        with QMutexLocker(self.mutex):
            processes_copy = self.processes.copy()
        for process in processes_copy:
            if process.poll() is None:  # Process is still running
                self.terminate_process(process)
        with QMutexLocker(self.mutex):
            self.processes.clear()


class NextRecordWorker(QObject):
    """Worker class for fetching the next MARC record in a separate thread."""

    record_fetched = pyqtSignal(Record)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, config: NextRecordWorkerConfig):
        """
        Initialize the NextRecordWorker.

        Args:
            config (NextRecordWorkerConfig): Configuration for the worker.
        """
        super().__init__()
        self.server_info = config.server_info
        self.query_type = config.query_type
        self.query = config.query
        self.start = config.start
        self.timeout = config.timeout
        self._cancel_requested = False

    def build_search_command(self) -> str:
        """
        Build the search command based on the query type.

        Returns:
            str: The search command string.
        """
        if self.query_type == QueryType.ISBN:
            search_command = f'find @attr 1=7 @attr 4=1 "{self.query}"\n'
        elif self.query_type == QueryType.TITLE_AUTHOR:
            title, author = self.query
            search_command = (f'find @and @attr 1=4 @attr 4=1 "{title}" '
                              f'@attr 1=1003 @attr 4=1 "{author}"\n')
        else:
            search_command = ""
        return search_command

    @pyqtSlot()
    def run(self):
        """Execute the worker to fetch the next record."""
        if self._cancel_requested:
            self.finished.emit()
            return

        server_name = self.server_info.get('name', 'Unknown Server')
        command = self._prepare_command(server_name)
        if not command:
            return

        cmd, full_command = command

        try:
            with subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW, ) as process:
                try:
                    stdout, _ = process.communicate(input=full_command, timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait()
                    self.error.emit(f"Timeout querying {server_name}.")
                    self.finished.emit()
                    return

                if self._cancel_requested:
                    process.terminate()
                    process.wait()
                    self.finished.emit()
                    return

                if "Present request out of range" in stdout:
                    self.error.emit("Requested more records than available. No more records.")
                else:
                    cleaned_data = clean_yaz_output(stdout)
                    marc_record = extract_marc_record(
                        cleaned_data, log_callback=self.log_message.emit
                        )
                    if marc_record:
                        self.record_fetched.emit(marc_record)
                    else:
                        self.error.emit("Failed to extract MARC record.")

        except (subprocess.CalledProcessError, OSError) as e:
            if not self._cancel_requested:
                self.error.emit(f"Error fetching record from {server_name}: {e}")
        finally:
            self.finished.emit()

    def _prepare_command(self, server_name: str) -> Optional[Tuple[List[str], str]]:
        """Prepare the command to execute."""
        try:
            cmd = ["yaz-client", f'{self.server_info["host"]}:{self.server_info["port"]}/'
                                 f'{self.server_info["database"]}', ]
            search_command = self.build_search_command()
            show_command = f"show {self.start}\n"
            full_command = search_command + show_command

            command_for_logging = full_command.replace("\n", " ")
            self.log_message.emit(
                f"Connecting to {server_name}: {' '.join(cmd)} with {command_for_logging}"
                )
            return cmd, full_command
        except KeyError as e:
            self.log_message.emit(f"Missing server key {e} in {server_name}.")
            return None

    def cancel(self):
        """Cancel the worker operation."""
        self._cancel_requested = True
