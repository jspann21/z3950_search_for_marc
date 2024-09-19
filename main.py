"""
Z39.50 MARC Record Search Application.

This module implements the main graphical user interface (GUI) for the Z39.50 MARC Record Search
application using PyQt5. It allows users to search MARC records by ISBN or Title & Author,
manage server configurations, display search results, navigate through records, and download
selected MARC records.

Key Components:
    - Z3950SearchApp: The primary QWidget-based class that sets up the UI, handles user
    interactions,
      manages worker threads, and orchestrates the search and display of MARC records.
    - WorkerManager: A helper class responsible for creating, managing, and cleaning up worker
    threads
      used for performing background search operations.

Features:
    - Search by ISBN with validation.
    - Search by Title and Author with combined query capabilities.
    - Filtering of servers based on location (USA or Worldwide).
    - Progress tracking through a progress bar.
    - Display of search results in a QListWidget.
    - Detailed view of selected MARC records.
    - Navigation between records with "Previous" and "Next" buttons.
    - Downloading of MARC records in `.mrc` format.
    - Comprehensive logging within the application for monitoring operations and debugging.

Usage:
    Run the application by executing the `main.py` script. Ensure that the `servers.json`
    configuration
    file is present in the same directory to load server settings.

Example:
    ```bash
    python main.py
    ```

Dependencies:
    - PyQt5
    - pymarc
    - json
    - subprocess
    - typing
    - dataclasses
    - enum
    - gc
    - re
    - sys
"""

import gc
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union, Dict, Any, cast

from PyQt5.QtCore import Qt, QThread, pyqtBoundSignal
from PyQt5.QtGui import QTextCursor, QIcon
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QGroupBox, QFileDialog, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QHBoxLayout, QLineEdit, QPushButton, QProgressBar, QTextEdit, QVBoxLayout, QWidget,
    )
from pymarc import Record

from utils import extract_marc_record, get_record_info, sanitize_filename, is_yaz_client_installed
from workers import Worker, NextRecordWorker, QueryType, WorkerConfig, NextRecordWorkerConfig


@dataclass
class WorkerInfo:
    """Dataclass to encapsulate worker and its thread."""
    worker: Optional[Worker] = None
    thread: Optional[QThread] = None


@dataclass
class SearchState:
    """Dataclass to manage the current search state."""
    current_marc_records: list = field(default_factory=list)
    current_record_index: int = 0
    total_records: int = 0
    current_server_info: Optional[dict] = None
    current_query_type: Optional[QueryType] = None
    current_query: Optional[Union[str, tuple]] = None


class LoggerMixin:
    """Mixin class to provide logging functionality."""

    ui: Dict[str, Any]

    def log_message(self, message: str):
        """Log messages to the log window."""
        if "log_window" in self.ui:
            self.ui["log_window"].append(message)
            self.ui["log_window"].moveCursor(QTextCursor.End)
            self.ui["log_window"].ensureCursorVisible()
        else:
            print(f"Log: {message}")


class WorkerManager:
    """Class to manage worker threads."""

    def __init__(self):
        self.worker_info = WorkerInfo()

    @staticmethod
    def create_worker_thread(worker_class, worker_args, worker_signals):
        """
        Create and start a worker thread.

        Args:
            worker_class: The worker class to instantiate.
            worker_args: Arguments to pass to the worker.
            worker_signals: Signals to connect to worker methods.

        Returns:
            Tuple of (worker, thread).
        """
        # Instantiate worker with appropriate config
        if worker_class == Worker:
            config = WorkerConfig(**worker_args)
            worker = worker_class(config=config)
        elif worker_class == NextRecordWorker:
            config = NextRecordWorkerConfig(**worker_args)
            worker = worker_class(config=config)
        else:
            # For other worker classes, pass arguments directly
            worker = worker_class(**worker_args)

        thread = QThread()
        worker.moveToThread(thread)

        # Connect worker signals to thread slots
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        # Connect additional signals provided in worker_signals
        for signal_name, handler in worker_signals.items():
            if hasattr(worker, signal_name):
                signal = getattr(worker, signal_name)
                signal = cast(pyqtBoundSignal, signal)  # Cast to pyqtBoundSignal for type checking
                signal.connect(handler)

        # Start the worker's run method when the thread starts
        thread.started.connect(worker.run)
        thread.start()

        return worker, thread

    def cleanup_worker_thread(self):
        """Clean up the existing worker thread if it's running."""
        try:
            if self.worker_info.worker and self.worker_info.thread:
                if self.worker_info.thread.isRunning():
                    self.worker_info.worker.cancel()
                    self.worker_info.thread.quit()
                    self.worker_info.thread.wait()
            # Regardless of the above, set worker and thread to None
            self.worker_info.worker = None
            self.worker_info.thread = None
        except RuntimeError as e:
            print(f"RuntimeError during cleanup: {e}")
            self.worker_info.worker = None
            self.worker_info.thread = None


class Z3950SearchApp(QWidget, LoggerMixin):
    """Main application class for the Z39.50 MARC Record Search."""

    def __init__(self):
        super().__init__()
        self.servers = []
        self.worker_manager = WorkerManager()
        self.next_record_worker_manager = WorkerManager()
        self.search_state = SearchState()
        self.timeout = 5
        self.ui = {}
        self.fetch_in_progress = False
        self._init_ui()

        # Check if yaz-client is installed
        if not is_yaz_client_installed():
            QMessageBox.critical(
                self, "Dependency Missing",
                "The 'yaz-client' tool is not installed or not found in your system's PATH.\n"
                "Please install YAZ from https://www.indexdata.com/resources/yaz/ and ensure it's "
                "accessible."
                )
            self.log_message("yaz-client is not installed or not found in PATH.")
            sys.exit(1)  # Exit the application as it cannot function without yaz-client

        self._load_servers()

    def _init_ui(self):
        """Initialize the user interface."""
        self._setup_window()
        self._create_search_boxes()
        self._create_progress_bar()
        self._create_results_window()
        self._create_record_details_window()
        self._create_navigation_buttons()
        self._create_log_window()
        self._setup_layout()

    def _setup_window(self):
        """Set up main window properties."""
        self.setWindowTitle("Z39.50 MARC Record Search")
        self.setGeometry(100, 100, 1000, 700)
        self.setWindowIcon(QIcon("app_icon.ico"))

    def _create_search_boxes(self):
        """Create ISBN and Title & Author search boxes along with location filters and thread
        selection."""
        # ISBN Search Box
        isbn_group = QGroupBox("Search by ISBN")
        isbn_layout = QVBoxLayout()
        self.ui["isbn_input"] = QLineEdit(self)
        self.ui["isbn_input"].setPlaceholderText("Enter ISBN")
        self.ui["search_isbn_button"] = QPushButton("Search ISBN", self)
        self.ui["search_isbn_button"].clicked.connect(self._start_search)
        isbn_layout.addWidget(self.ui["isbn_input"])
        isbn_layout.addWidget(self.ui["search_isbn_button"])
        isbn_group.setLayout(isbn_layout)

        # Title & Author Search Box
        title_author_group = QGroupBox("Search by Title && Author")
        title_author_layout = QVBoxLayout()
        self.ui["title_input"] = QLineEdit(self)
        self.ui["title_input"].setPlaceholderText("Enter Title")
        self.ui["author_input"] = QLineEdit(self)
        self.ui["author_input"].setPlaceholderText("Enter Author")
        self.ui["search_title_author_button"] = QPushButton("Search Title && Author", self)
        self.ui["search_title_author_button"].clicked.connect(self._start_search)
        title_author_layout.addWidget(self.ui["title_input"])
        title_author_layout.addWidget(self.ui["author_input"])
        title_author_layout.addWidget(self.ui["search_title_author_button"])
        title_author_group.setLayout(title_author_layout)

        # Cancel Button
        self.ui["cancel_button"] = QPushButton("Cancel", self)
        self.ui["cancel_button"].setEnabled(False)
        self.ui["cancel_button"].setFixedHeight(60)
        self.ui["cancel_button"].clicked.connect(self._cancel_search)

        # Location Filters
        location_group = QGroupBox("Filter by Location")
        location_layout = QVBoxLayout()

        self.ui["usa_checkbox"] = QCheckBox("USA", self)
        self.ui["usa_checkbox"].setChecked(True)  # Checked by default
        self.ui["worldwide_checkbox"] = QCheckBox("Worldwide", self)
        self.ui["worldwide_checkbox"].setChecked(True)  # Checked by default

        location_layout.addWidget(self.ui["usa_checkbox"])
        location_layout.addWidget(self.ui["worldwide_checkbox"])
        location_group.setLayout(location_layout)

        # Add all components to the top layout
        self.ui["top_layout"] = QHBoxLayout()
        self.ui["top_layout"].addWidget(isbn_group)
        self.ui["top_layout"].addWidget(title_author_group)
        self.ui["top_layout"].addWidget(location_group)
        self.ui["top_layout"].addWidget(self.ui["cancel_button"])

    def _create_progress_bar(self):
        """Create the progress bar."""
        self.ui["progress_bar"] = QProgressBar(self)
        self.ui["progress_bar"].setRange(0, 100)
        self.ui["progress_bar"].setValue(0)

    def _create_results_window(self):
        """Create the results window."""
        self.ui["results_window"] = QListWidget(self)
        self.ui["results_window"].itemClicked.connect(self._on_result_clicked)

    def _create_record_details_window(self):
        """Create the record details window."""
        self.ui["record_details_window"] = QTextEdit(self)
        self.ui["record_details_window"].setReadOnly(True)

    def _create_navigation_buttons(self):
        """Create navigation buttons."""
        self.ui["download_button"] = QPushButton("Download Record", self)
        self.ui["download_button"].setEnabled(False)
        self.ui["download_button"].clicked.connect(self._download_marc_record)

        self.ui["prev_record_button"] = QPushButton("Previous Record", self)
        self.ui["prev_record_button"].setEnabled(False)
        self.ui["prev_record_button"].clicked.connect(self._show_prev_record)

        self.ui["next_record_button"] = QPushButton("Next Record", self)
        self.ui["next_record_button"].setEnabled(False)
        self.ui["next_record_button"].clicked.connect(self._show_next_record)

        self.ui["nav_layout"] = QHBoxLayout()
        self.ui["nav_layout"].addWidget(self.ui["prev_record_button"])
        self.ui["nav_layout"].addWidget(self.ui["next_record_button"])

    def _create_log_window(self):
        """Create the log window."""
        self.ui["log_window"] = QTextEdit(self)
        self.ui["log_window"].setReadOnly(True)
        self.ui["log_window"].setMaximumHeight(150)

    def _setup_layout(self):
        """Set up the main layout."""
        main_layout = QVBoxLayout()
        main_layout.addLayout(self.ui["top_layout"])
        main_layout.addWidget(self.ui["progress_bar"])
        main_layout.addWidget(QLabel("Search Results:"))
        main_layout.addWidget(self.ui["results_window"])
        main_layout.addWidget(QLabel("Record Details:"))
        main_layout.addWidget(self.ui["record_details_window"])
        main_layout.addLayout(self.ui["nav_layout"])
        main_layout.addWidget(self.ui["download_button"])
        main_layout.addWidget(QLabel("Log:"))
        main_layout.addWidget(self.ui["log_window"])
        self.setLayout(main_layout)

    def _load_servers(self):
        """Load server configurations from a JSON file."""
        try:
            with open("servers.json", "r", encoding="utf-8") as f:
                self.servers = json.load(f)
            self.log_message(f"Loaded {len(self.servers)} servers from 'servers.json'.")
        except FileNotFoundError as e:
            self.servers = []
            self.log_message(f"Server configuration file not found: {e}")
            QMessageBox.critical(
                self, "Configuration Error", "The 'servers.json' file was not found."
                )
        except json.JSONDecodeError as e:
            self.servers = []
            self.log_message(f"Failed to parse JSON from servers.json: {e}")
            QMessageBox.critical(
                self, "Configuration Error",
                "Failed to parse 'servers.json'. Please check the JSON syntax."
                )
        except OSError as e:
            self.servers = []
            self.log_message(f"OS error while loading servers.json: {e}")
            QMessageBox.critical(
                self, "Configuration Error", "An OS error occurred while loading 'servers.json'."
                )

    @staticmethod
    def validate_isbn(isbn: str) -> bool:
        """
        Validate the ISBN using regex and checksum validation.

        Args:
            isbn (str): The ISBN string to validate.

        Returns:
            bool: True if valid, False otherwise.
        """
        isbn = isbn.replace("-", "").replace(" ", "").upper()
        regex = re.compile(r"^(97[89])?\d{9}[\dX]$")

        if not regex.match(isbn):
            return False

        is_valid = False
        if len(isbn) == 10:
            try:
                total = sum(
                    (10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(isbn)
                    )
                is_valid = total % 11 == 0
            except ValueError:
                pass  # is_valid remains False
        elif len(isbn) == 13 and "X" not in isbn:
            try:
                total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(isbn))
                is_valid = total % 10 == 0
            except ValueError:
                pass  # is_valid remains False

        return is_valid

    def _manage_navigation_buttons(self, prev_enabled: bool, next_enabled: bool):
        """Manage the enabled/disabled state of navigation buttons."""
        self.ui["prev_record_button"].setEnabled(prev_enabled)
        self.ui["next_record_button"].setEnabled(next_enabled)

    def _toggle_search_buttons(self, enabled: bool):
        """
        Enable or disable search buttons.

        Args:
            enabled (bool): True to enable, False to disable.
        """
        self.ui["search_isbn_button"].setEnabled(enabled)
        self.ui["search_title_author_button"].setEnabled(enabled)
        self.ui["cancel_button"].setEnabled(not enabled)

    def _cancel_search(self):
        """Cancel the ongoing search."""
        self.worker_manager.cleanup_worker_thread()

        self.ui["progress_bar"].setValue(0)
        self._toggle_search_buttons(True)
        self.log_message("Search cancelled.")
        self.fetch_in_progress = False
        self._manage_navigation_buttons(
            prev_enabled=self.search_state.current_record_index > 0,
            next_enabled=self.search_state.current_record_index < self.search_state.total_records
                         - 1
            )

    def _update_navigation_buttons(self):
        """Enable or disable navigation buttons based on the current record index."""
        self._manage_navigation_buttons(
            prev_enabled=self.search_state.current_record_index > 0,
            next_enabled=self.search_state.current_record_index < self.search_state.total_records
                         - 1
            )

    def _start_search(self):
        """Start a search based on the input fields (ISBN or Title & Author)."""
        # Validate and prepare search parameters
        if not self._ensure_servers_loaded():
            return

        selected_locations = self._get_selected_locations()

        if not self._ensure_locations_selected(selected_locations):
            return

        filtered_servers = self._filter_servers_by_location(selected_locations)

        if not self._ensure_filtered_servers(filtered_servers):
            return

        sender = self.sender()
        if sender == self.ui["search_isbn_button"]:
            if not self._prepare_isbn_search():
                return
        elif sender == self.ui["search_title_author_button"]:
            if not self._prepare_title_author_search():
                return
        else:
            self.log_message("Unknown search type.")
            return

        self.ui["record_details_window"].clear()

        # Clear cached records
        self.search_state.current_marc_records = []
        self.search_state.total_records = 0
        self.search_state.current_record_index = 0
        self.ui["results_window"].clear()

        self.log_message(
            f"Starting {self.search_state.current_query_type.value} search with query: "
            f"{self.search_state.current_query}"
            )
        self.ui["progress_bar"].setValue(0)
        self.ui["results_window"].clear()

        self._manage_navigation_buttons(prev_enabled=False, next_enabled=False)

        # Ensure any old worker thread is properly cleaned up before starting a new search
        self.worker_manager.cleanup_worker_thread()

        worker_args = {
            "servers": filtered_servers, "query_type": self.search_state.current_query_type,
            "query": self.search_state.current_query, "start": 1, "timeout": self.timeout,
            "max_threads": 50,  # Adjust as needed
            }
        worker_signals = {
            "progress": self.ui["progress_bar"].setValue, "log_message": self.log_message,
            "result_found": self._display_result, "finished": self._on_worker_finished,
            "error": self._handle_worker_error,
            }
        self.worker_manager.worker_info.worker, self.worker_manager.worker_info.thread = (
            self.worker_manager.create_worker_thread(
                Worker, worker_args, worker_signals
                ))
        self._toggle_search_buttons(False)

    def _ensure_servers_loaded(self) -> bool:
        """Ensure servers are loaded.

        Returns:
            bool: True if servers are loaded, False otherwise.
        """
        if not self.servers:
            self._load_servers()
            if not self.servers:
                self.log_message(
                    "No servers loaded. Please ensure 'servers.json' is in the correct location."
                    )
                QMessageBox.critical(
                    self, "Server Load Error", "No servers loaded. Please check 'servers.json'."
                    )
                return False
        return True

    def _get_selected_locations(self) -> list:
        """Get the selected locations from checkboxes.

        Returns:
            list: A list of selected locations.
        """
        selected_locations = []
        if self.ui["usa_checkbox"].isChecked():
            selected_locations.append("USA")
        if self.ui["worldwide_checkbox"].isChecked():
            selected_locations.append("Worldwide")
        return selected_locations

    def _ensure_locations_selected(self, selected_locations: list) -> bool:
        """Ensure at least one location is selected.

        Args:
            selected_locations (list): List of selected locations.

        Returns:
            bool: True if at least one location is selected, False otherwise.
        """
        if not selected_locations:
            self.log_message("Please select at least one location to include in the search.")
            QMessageBox.warning(
                self, "Selection Error",
                "Please select at least one location to include in the search."
                )
            return False
        return True

    def _filter_servers_by_location(self, selected_locations: list) -> list:
        """Filter servers based on selected locations.

        Args:
            selected_locations (list): List of selected locations.

        Returns:
            list: A list of servers matching the selected locations.
        """
        return [server for server in self.servers if server.get("location") in selected_locations]

    def _ensure_filtered_servers(self, filtered_servers: list) -> bool:
        """Ensure there are servers after filtering.

        Args:
            filtered_servers (list): List of filtered servers.

        Returns:
            bool: True if there are filtered servers, False otherwise.
        """
        if not filtered_servers:
            self.log_message("No servers match the selected location filters.")
            QMessageBox.warning(
                self, "Filter Error", "No servers match the selected location filters."
                )
            return False
        return True

    def _prepare_isbn_search(self) -> bool:
        """Prepare for ISBN search.

        Returns:
            bool: True if preparation is successful, False otherwise.
        """
        query_type = QueryType.ISBN
        query = self.ui["isbn_input"].text().strip()

        if not query:
            self.log_message("Please enter an ISBN.")
            QMessageBox.warning(self, "Input Error", "Please enter an ISBN.")
            return False

        # Validate ISBN
        if not self.validate_isbn(query):
            self.log_message("Invalid ISBN. Please enter a valid ISBN.")
            QMessageBox.warning(
                self, "Validation Error", "Invalid ISBN. Please enter a valid ISBN."
                )
            return False

        self.search_state.current_query_type = query_type
        self.search_state.current_query = query
        return True

    def _prepare_title_author_search(self) -> bool:
        """Prepare for Title and Author search.

        Returns:
            bool: True if preparation is successful, False otherwise.
        """
        query_type = QueryType.TITLE_AUTHOR
        title = self.ui["title_input"].text().strip()
        author = self.ui["author_input"].text().strip()

        if not title or not author:
            self.log_message("Please enter both Title and Author.")
            QMessageBox.warning(self, "Input Error", "Please enter both Title and Author.")
            return False

        query = (title, author)
        self.search_state.current_query_type = query_type
        self.search_state.current_query = query
        return True

    def _on_worker_finished(self):
        """Handle worker and thread cleanup."""
        was_canceled = (
            self.worker_manager.worker_info.worker.cancel_requested if
            self.worker_manager.worker_info.worker else True)

        self.worker_manager.cleanup_worker_thread()

        self._search_finished(was_canceled)

    def _search_finished(self, was_canceled: bool = False):
        """Handle the completion of a search.

        Args:
            was_canceled (bool, optional): Indicates if the search was canceled. Defaults to False.
        """
        self._toggle_search_buttons(True)

        if not was_canceled:
            # Only set the progress bar to 100% if the search was not cancelled
            self.ui["progress_bar"].setValue(100)
            self.log_message("Search completed.")
        else:
            self.ui["progress_bar"].setValue(0)  # Reset progress if search was cancelled

        # Enable navigation buttons after search completes or is cancelled
        self._update_navigation_buttons()
        self.fetch_in_progress = False

    def _handle_worker_error(self, message: str):
        """Handle errors emitted by the Worker.

        Args:
            message (str): The error message.
        """
        self.log_message(f"Error: {message}")
        QMessageBox.warning(self, "Search Error", message)
        self._toggle_search_buttons(True)
        self.fetch_in_progress = False

    def _display_result(self, result: dict):
        """Display search results.

        Args:

            result (dict): A dictionary containing search result details.
        """
        summary = f"{result['summary']} - {result['number_of_hits']} hits"
        self.log_message(f"Displaying result from {summary}")

        item = QListWidgetItem(summary)
        item.setData(Qt.UserRole, result)
        self.ui["results_window"].addItem(item)

    def _on_result_clicked(self, item: QListWidgetItem):
        """Handle clicking on a search result.

        Args:
            item (QListWidgetItem): The clicked QListWidgetItem.
        """
        result = item.data(Qt.UserRole)
        self.search_state.current_server_info = self._get_server_by_summary(result["summary"])
        raw_data = result["raw_data"]

        # Use extract_marc_record directly from utils.py
        marc_record = extract_marc_record(raw_data, log_callback=self.log_message)
        if marc_record:
            self.search_state.current_marc_records = [marc_record]  # Store as a single-record list
        else:
            self.search_state.current_marc_records = []
        self.search_state.total_records = result["number_of_hits"]
        self.search_state.current_record_index = 0
        self._display_current_record()
        self._update_navigation_buttons()

    def _get_server_by_summary(self, summary: str) -> Optional[dict]:
        """Helper function to retrieve server dictionary by its summary.

        Args:
            summary (str): The summary string to match.

        Returns:
            dict or None: The matching server dictionary or None if not found.
        """
        summary_server_name = summary.split(" - ")[0]
        for server in self.servers:
            server_summary = (
                f"{server['name']} ({server['host']}:{server['port']}/{server['database']})")
            if server_summary == summary_server_name:
                return server
        return None

    def _display_current_record(self):
        """Display the current MARC record."""
        if (self.search_state.current_marc_records and self.search_state.current_record_index < len(
                self.search_state.current_marc_records
                )):
            record = self.search_state.current_marc_records[self.search_state.current_record_index]
            formatted_record = []

            for fld in record.fields:
                if fld.is_control_field():
                    # For control fields (tags 001-009), just show the tag and data
                    formatted_record.append(f"{fld.tag}    {fld.data}")
                else:
                    # For data fields, show the tag, indicators, and subfields
                    indicators = "".join(fld.indicators)  # Join the indicators

                    # Correctly extract subfield codes and values from Subfield objects
                    subfields = " ".join(
                        f"${subfield.code} {subfield.value}" for subfield in fld.subfields
                        )

                    formatted_record.append(f"{fld.tag} {indicators} {subfields}")

            # Display the formatted record
            self.ui["record_details_window"].setPlainText(
                "\n".join(formatted_record)
                )
            self.ui["download_button"].setEnabled(True)
            self.log_message("Record displayed.")
        else:
            self.ui["record_details_window"].setPlainText("No record available.")
            self.ui["download_button"].setEnabled(False)
            self.log_message("No record available to display.")

        self._update_navigation_buttons()

    def _show_next_record(self):
        """Navigate to the next record by fetching it in a separate thread."""
        if self.fetch_in_progress:
            self.log_message("Next record fetch is already in progress.")
            QMessageBox.information(
                self, "Info", "Next record is already being fetched. Please wait."
                )
            return

        # Attempt to check if a fetch is already in progress
        try:
            if (
                    self.next_record_worker_manager.worker_info.worker and
                    self.next_record_worker_manager.worker_info.thread and
                    self.next_record_worker_manager.worker_info.thread.isRunning()):
                self.log_message("Next record fetch is already in progress.")
                QMessageBox.information(
                    self, "Info", "Next record is already being fetched. Please wait."
                    )
                return
        except RuntimeError:
            self.log_message("Thread has been deleted unexpectedly.")  # Proceed safely

        self.fetch_in_progress = True
        self._manage_navigation_buttons(prev_enabled=False, next_enabled=False)

        # Check if we have already fetched the next record
        if (self.search_state.current_record_index + 1 < len(
                self.search_state.current_marc_records
                )):
            # We have the next record already, so increment the index and display it
            self.search_state.current_record_index += 1
            self._display_current_record()
            self.log_message("Displaying previously fetched record.")
            self._manage_navigation_buttons(
                prev_enabled=self.search_state.current_record_index > 0,
                next_enabled=self.search_state.current_record_index <
                             self.search_state.total_records - 1
                )
            self.fetch_in_progress = False
        else:
            # Check if there are more records to fetch
            if self.search_state.current_record_index + 1 < self.search_state.total_records:
                start = self.search_state.current_record_index + 2  # Record number to fetch

                # Ensure any old worker thread is properly cleaned up before starting a new fetch
                self.next_record_worker_manager.cleanup_worker_thread()

                worker_args = {
                    "server_info": self.search_state.current_server_info,
                    "query_type": self.search_state.current_query_type,
                    "query": self.search_state.current_query, "start": start,
                    "timeout": self.timeout,
                    }
                worker_signals = {
                    "record_fetched": self._handle_next_record_fetched,
                    "error": self._handle_next_record_error,
                    "finished": self._on_next_record_worker_finished,
                    "log_message": self.log_message,
                    }
                (self.next_record_worker_manager.worker_info.worker,
                 self.next_record_worker_manager.worker_info.thread) = (
                    self.next_record_worker_manager.create_worker_thread(
                        NextRecordWorker, worker_args, worker_signals
                        ))

            else:
                self.log_message("No more records to display.")
                QMessageBox.information(self, "Info", "No more records to display.")
                self._manage_navigation_buttons(
                    prev_enabled=self.search_state.current_record_index > 0, next_enabled=False
                    )
                self.fetch_in_progress = False

    def _on_next_record_worker_finished(self):
        """Handle the completion of the next record worker."""
        self.next_record_worker_manager.cleanup_worker_thread()
        self._manage_navigation_buttons(
            prev_enabled=self.search_state.current_record_index > 0,
            next_enabled=self.search_state.current_record_index < self.search_state.total_records
                         - 1
            )
        self.fetch_in_progress = False

    def _handle_next_record_fetched(self, marc_record: Record):
        """Handle the MARC record fetched by the worker.

        Args:
            marc_record (Record): The fetched MARC Record object.
        """
        self.search_state.current_marc_records.append(marc_record)
        self.search_state.current_record_index += 1
        self._display_current_record()
        self._manage_navigation_buttons(
            prev_enabled=True,
            next_enabled=self.search_state.current_record_index < self.search_state.total_records
                         - 1
            )
        self.fetch_in_progress = False

    def _handle_next_record_error(self, message: str):
        """Handle errors from the NextRecordWorker.

        Args:
            message (str): Error message.
        """
        self.log_message(f"Error fetching next record: {message}")
        QMessageBox.warning(self, "Record Fetch Error", message)
        self._manage_navigation_buttons(
            prev_enabled=self.search_state.current_record_index > 0, next_enabled=True
            # Allow retry
            )
        self.fetch_in_progress = False

    def _show_prev_record(self):
        """Navigate to the previous record."""
        if self.search_state.current_record_index > 0:
            self.search_state.current_record_index -= 1
            self._display_current_record()
            self.log_message("Displaying previously fetched record.")
            self._manage_navigation_buttons(
                prev_enabled=self.search_state.current_record_index > 0,
                next_enabled=self.search_state.current_record_index <
                             self.search_state.total_records - 1
                )
        else:
            self.log_message("Already at the first record.")
            QMessageBox.information(self, "Info", "Already at the first record.")

    def _download_marc_record(self):
        """Download the currently displayed MARC record as a file."""
        if self.search_state.current_marc_records:
            record = self.search_state.current_marc_records[self.search_state.current_record_index]

            # Check if record is a proper pymarc Record object
            if isinstance(record, Record):
                author, title = get_record_info(record)
                # Construct the sanitized filename
                raw_filename = f"{author}_{title}"
                sanitized_filename = sanitize_filename(raw_filename)
                default_filename = Path.home() / "Downloads" / f"{sanitized_filename}.mrc"

                # Ensure the Downloads directory exists; if not, use home directory
                if not default_filename.parent.exists():
                    self.log_message("Downloads folder not found. Using home directory for saving.")
                    default_filename = Path.home() / f"{sanitized_filename}.mrc"

                # Check write permissions to the target directory
                if not os.access(default_filename.parent, os.W_OK):
                    QMessageBox.critical(
                        self, "Permission Denied",
                        f"Cannot write to the directory: {default_filename.parent}\n"
                        "Please check your permissions and try again."
                        )
                    self.log_message(f"Permission denied for directory: {default_filename.parent}")
                    return

                file_name, _ = QFileDialog.getSaveFileName(
                    self, "Save MARC Record", str(default_filename), "MARC Files (*.mrc)"
                    )
                if file_name:
                    try:
                        with open(file_name, "wb") as file:
                            file.write(record.as_marc())
                        QMessageBox.information(
                            self, "Success", "MARC record saved successfully!"
                            )
                        self.log_message(f"MARC record saved to {file_name}.")
                    except PermissionError as e:
                        QMessageBox.critical(
                            self, "Permission Error",
                            f"Insufficient permissions to save the file: {e}"
                            )
                        self.log_message(
                            f"PermissionError: Failed to save MARC record to {file_name}: {e}"
                            )
                    except IOError as e:
                        QMessageBox.warning(
                            self, "IO Error", f"Failed to save file: {e}"
                            )
                        self.log_message(f"IOError: Failed to save MARC record to {file_name}: {e}")
            else:
                QMessageBox.warning(self, "Error", "Invalid MARC record format.")
                self.log_message("Attempted to save an invalid MARC record.")
        else:
            QMessageBox.warning(self, "Error", "No MARC record to save.")
            self.log_message("No MARC record available to save.")

    def closeEvent(self, event):
        """Ensure the worker thread and subprocesses are properly terminated when the application
        is closed.

        Args:
            event: The close event.
        """
        self.log_message("Closing application and cleaning up workers...")
        self.worker_manager.cleanup_worker_thread()
        self.next_record_worker_manager.cleanup_worker_thread()
        self.fetch_in_progress = False

        # Clear memory and force garbage collection
        self.search_state.current_marc_records.clear()
        gc.collect()

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = Z3950SearchApp()
    ex.show()
    sys.exit(app.exec_())
