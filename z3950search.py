"""
Z39.50 MARC Record Search Application

This module implements a PyQt5-based graphical user interface (GUI)
application for performing Z39.50 searches across multiple servers
to retrieve MARC records. The application supports searching by ISBN,
Title, and Author. It fetches MARC records from configured Z39.50
servers and displays the retrieved records in a user-friendly manner.

Key Features:
- Allows users to search by ISBN or by a combination of Title and Author.
- Communicates with multiple Z39.50 servers concurrently to maximize
search coverage.
- Displays retrieved MARC records in a formatted view and provides
navigation to move between records.
- Supports downloading MARC records to a file.
- Displays search progress and logs for user feedback.
- Includes a cancel mechanism to stop long-running searches.
- Efficient memory management and proper resource cleanup during process
termination or cancellation.

Modules:
- Worker: Handles the execution of searches in a separate thread, running
the YAZ client and processing responses.
- Z3950SearchApp: The main application class responsible for managing the
GUI, interacting with the user, and handling the results.

Dependencies:
- PyQt5: Provides the graphical user interface components.
- pymarc: Used to process MARC records.
- subprocess: Used to invoke the YAZ client for querying Z39.50 servers.
- json: For loading server configuration.
- re: For regular expression operations.

Usage:
Assumes yaz-client is installed and available in the PATH.
    https://www.indexdata.com/resources/software/yaz/
Run the module as a standalone script to start the GUI application.
Users can enter ISBN or Title/Author combinations, initiate searches,
and view/download MARC records.

Example:
$ python z3950search.py

"""

import sys
import subprocess
import json
import re
import gc
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QLabel,
    QProgressBar,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QMessageBox,
    QGroupBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
from pymarc import Record, Field, Subfield


class Worker(QObject):
    """Worker class for handling Z39.50 searches in a separate thread."""

    finished = pyqtSignal()
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_found = pyqtSignal(dict)

    def __init__(self, servers, query_type, query, start=1):
        """
        Initializes the Worker object.

        Args:
            servers (list): A list of Z39.50 server configurations.
            query_type (str): The type of query ('isbn' or 'title_author').
            query (str or tuple): The search query (either an ISBN or a tuple of title and author).
            start (int): The record index to start retrieving from (default is 1).
        """
        super().__init__()
        self.servers = servers
        self.query_type = query_type
        self.query = query
        self.start = start
        self.timeout = 10
        self.cancel_requested = False
        self.process = None

    def run(self):
        """
        Executes the Z39.50 searches in a separate thread.

        It loops over the list of servers, sending the search query to each,
        processing the results, and emitting progress signals.
        """
        total_servers = len(self.servers)
        if total_servers == 0:
            self.finished.emit()
            return
        self.log_message.emit(f"Total servers to query: {total_servers}")

        for server in self.servers:
            if self.cancel_requested:  # Check if cancellation was requested
                break

            current_server_name = server.get("name", "Unknown Server")
            try:
                self.run_yaz_client(server)
            except subprocess.TimeoutExpired:
                self.log_message.emit(f"Connection to {current_server_name} timed out.")
            except subprocess.CalledProcessError as e:
                self.log_message.emit(
                    f"Subprocess error querying {current_server_name}: {e}"
                )
            except OSError as e:
                self.log_message.emit(f"OS error querying {current_server_name}: {e}")
            except Exception as e:
                self.log_message.emit(
                    f"Unexpected error querying {current_server_name}: {e}"
                )
                raise  # Optionally re-raise the exception after logging

            progress = int((self.servers.index(server) + 1) / total_servers * 100)
            self.progress.emit(progress)

        if not self.cancel_requested:  # Prevent emitting 100% if canceled
            self.progress.emit(100)
        self.finished.emit()

    def run_yaz_client(self, server):
        """Run the YAZ client to query the server and retrieve records."""
        if self.cancel_requested:
            return  # Exit early if the search is cancelled

        load_server_name = server.get("name", "Unknown Server")

        try:
            cmd, full_command = self.build_command(server)
            command_for_logging = full_command.replace("\n", " ")
            self.log_message.emit(
                f"Connecting to {load_server_name} with command: {cmd} with {command_for_logging}"
            )

            with subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,  # Suppress terminal window
            ) as process:
                self.process = process
                stdout, _ = process.communicate(full_command, timeout=self.timeout)

                if self.cancel_requested:
                    self.terminate_process()
                    return

                if process.returncode == 0 and stdout.strip():
                    self.handle_successful_response(stdout, server)
                else:
                    self.log_message.emit(f"No records found in {load_server_name}.")

        except subprocess.TimeoutExpired:
            self.log_message.emit(f"Connection to {load_server_name} timed out.")
        except (subprocess.CalledProcessError, OSError, ValueError) as e:
            self.log_message.emit(f"Error querying {load_server_name}: {e}")
        except Exception as e:
            if not self.cancel_requested:
                self.log_message.emit(
                    f"Unexpected error querying {load_server_name}: {e}"
                )
            raise
        finally:
            self.process = None

    def build_command(self, server):
        """Build the command for running the YAZ client."""
        full_command = self.build_yaz_command(self.start)
        cmd = [
            "yaz-client",
            f'{server["host"]}:{server["port"]}/{server["database"]}',
        ]
        return cmd, full_command

    def handle_successful_response(self, stdout, server):
        """Handle the successful response from the YAZ client."""
        cleaned_data = clean_yaz_output(stdout)
        hits_line = next(
            (line for line in stdout.splitlines() if "Number of hits:" in line), None
        )
        number_of_hits = (
            int(hits_line.split(":")[1].split(",")[0].strip()) if hits_line else 0
        )

        if number_of_hits > 0:
            result = {
                "summary": f"{server['name']} ({server['host']}:{server['port']})",
                "raw_data": cleaned_data,
                "number_of_hits": number_of_hits,
            }
            self.result_found.emit(result)
        else:
            self.log_message.emit(f"No records found in {server['name']}.")

    def terminate_process(self):
        """Terminate the process if the search is cancelled."""
        if self.process:
            self.process.terminate()
            self.process = None

    def cancel(self):
        """Method to be called when cancel is requested."""
        self.cancel_requested = True
        if self.process:
            self.process.terminate()  # Terminate the process if it's running
            self.process = None

    def build_yaz_command(self, start):
        """Construct the search command based on the query type and record index."""
        if self.query_type == "isbn":
            search_command = f'find @attr 1=7 @attr 4=1 "{self.query}"\n'
        elif self.query_type == "title_author":
            title, author = self.query
            search_command = (
                f'find @and @attr 1=4 @attr 4=1 "{title}" '
                f'@attr 1=1003 @attr 4=1 "{author}"\n'
            )
        else:
            search_command = ""
        show_command = f"show {start}\n"
        return search_command + show_command


def clean_yaz_output(raw_data):
    """Clean YAZ client log output and return only the MARC record data."""
    marc_lines = []
    for line in raw_data.splitlines():
        if len(line) >= 4 and line[:3].isdigit() and line[3] == " ":
            tag = line[:3]  # Extract the MARC tag
            tag_int = int(tag)

            # Ignore control fields (000-009) and tags 900 or greater
            if 10 <= tag_int < 900:
                marc_lines.append(line)
    return "\n".join(marc_lines)


def get_record_info(record):
    """Extract author and title from the MARC record."""
    author = title = "MARC_Record"
    for field in record.get_fields("100", "110", "111", "245"):
        if field.tag.startswith("1"):
            author = re.sub(r"[^\w\s]", "", field["a"]).strip()
        if field.tag == "245":
            title = re.sub(r"[^\w\s]", "", field["a"]).strip()
    return author, title


class Z3950SearchApp(QWidget):
    """Main application class for the Z39.50 MARC Record Search."""

    def __init__(self):
        super().__init__()
        self.servers = None
        self.next_record_button = None
        self.prev_record_button = None
        self.download_button = None
        self.log_window = None
        self.record_details_window = None
        self.results_window = None
        self.progress_bar = None
        self.cancel_button = None
        self.search_title_author_button = None
        self.author_input = None
        self.title_input = None
        self.search_isbn_button = None
        self.isbn_input = None
        self.init_ui()
        self.load_servers()
        self.process = None
        self.worker = None
        self.worker_thread = None
        self.current_marc_records = []
        self.current_record_index = 0
        self.total_records = 0
        self.current_server_info = None  # Store the current server info
        self.current_query_type = None  # Store the current query type
        self.current_query = None  # Store the current query
        self.timeout = 5  # Set a default timeout value (in seconds)

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Z39.50 MARC Record Search")
        self.setGeometry(100, 100, 800, 600)
        main_layout = QVBoxLayout()

        # ISBN Search Box
        isbn_group = QGroupBox("Search by ISBN")
        isbn_layout = QVBoxLayout()
        self.isbn_input = QLineEdit(self)
        self.isbn_input.setPlaceholderText("ISBN")
        self.search_isbn_button = QPushButton("Search ISBN", self)
        self.search_isbn_button.clicked.connect(self.start_search)
        isbn_layout.addWidget(self.isbn_input)
        isbn_layout.addWidget(self.search_isbn_button)
        isbn_group.setLayout(isbn_layout)

        # Title & Author Search Box
        title_author_group = QGroupBox("Search by Title && Author")
        title_author_layout = QVBoxLayout()
        self.title_input = QLineEdit(self)
        self.title_input.setPlaceholderText("Title")
        self.author_input = QLineEdit(self)
        self.author_input.setPlaceholderText("Author")
        self.search_title_author_button = QPushButton("Search Title && Author", self)
        self.search_title_author_button.clicked.connect(self.start_search)
        title_author_layout.addWidget(self.title_input)
        title_author_layout.addWidget(self.author_input)
        title_author_layout.addWidget(self.search_title_author_button)
        title_author_group.setLayout(title_author_layout)

        # Cancel Button
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setFixedHeight(60)
        self.cancel_button.clicked.connect(self.cancel_search)

        # Add all components to the layout
        top_layout = QHBoxLayout()
        top_layout.addWidget(isbn_group)
        top_layout.addWidget(title_author_group)
        top_layout.addWidget(self.cancel_button)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)

        self.results_window = QListWidget(self)
        self.results_window.itemClicked.connect(self.on_result_clicked)

        self.record_details_window = QTextEdit(self)
        self.record_details_window.setReadOnly(True)

        self.log_window = QTextEdit(self)
        self.log_window.setReadOnly(True)
        self.log_window.setMaximumHeight(150)

        self.download_button = QPushButton("Download Record", self)
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self.download_marc_record)

        self.prev_record_button = QPushButton("Previous Record", self)
        self.prev_record_button.setEnabled(False)
        self.prev_record_button.clicked.connect(self.show_prev_record)

        self.next_record_button = QPushButton("Next Record", self)
        self.next_record_button.setEnabled(False)
        self.next_record_button.clicked.connect(self.show_next_record)

        nav_layout = QHBoxLayout()
        nav_layout.addWidget(self.prev_record_button)
        nav_layout.addWidget(self.next_record_button)

        # Add all components to the main layout
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(QLabel("Search Results:"))
        main_layout.addWidget(self.results_window)
        main_layout.addWidget(QLabel("Record Details:"))
        main_layout.addWidget(self.record_details_window)
        main_layout.addLayout(nav_layout)
        main_layout.addWidget(self.download_button)
        main_layout.addWidget(QLabel("Log:"))
        main_layout.addWidget(self.log_window)

        self.setLayout(main_layout)

    def load_servers(self):
        """Load server configurations from a JSON file."""
        try:
            with open("servers.json", "r", encoding="utf-8") as f:
                self.servers = json.load(f)
            self.log(f"Loaded {len(self.servers)} servers from 'servers.json'.")
        except FileNotFoundError as e:
            self.servers = []
            self.log(f"Server configuration file not found: {e}")
        except json.JSONDecodeError as e:
            self.servers = []
            self.log(f"Failed to parse JSON from servers.json: {e}")
        except OSError as e:
            self.servers = []
            self.log(f"OS error while loading servers.json: {e}")

    def log(self, message):
        """Log messages to the log window."""
        self.log_window.append(message)
        self.log_window.ensureCursorVisible()  # Ensure the cursor is visible (scroll to bottom)

    def start_search(self):
        """Start a search based on the input fields (ISBN or Title & Author)."""

        # Check if servers are loaded
        if not self.servers:
            self.load_servers()
            if not self.servers:
                self.log(
                    "No servers loaded. Please ensure 'servers.json' is in the correct "
                    "location."
                )
                return

        # Determine which button was clicked
        sender = self.sender()
        if sender == self.search_isbn_button:
            query_type = "isbn"
            query = self.isbn_input.text().strip()

            if not query:
                self.log("Please enter an ISBN.")
                return

            # Validate ISBN
            if not self.validate_isbn(query):
                self.log("Invalid ISBN. Please enter a valid ISBN.")
                return

        elif sender == self.search_title_author_button:
            query_type = "title_author"
            title = self.title_input.text().strip()
            author = self.author_input.text().strip()

            if not title or not author:
                self.log("Please enter both Title and Author.")
                return

            query = (title, author)
        else:
            self.log("Unknown search type.")
            return

        self.record_details_window.clear()

        # Clear cached records
        self.current_marc_records = []
        self.total_records = 0
        self.current_record_index = 0
        self.results_window.clear()

        self.log(f"Starting {query_type} search with query: {query}")
        self.progress_bar.setValue(0)
        self.results_window.clear()

        self.current_query_type = query_type
        self.current_query = query

        self.prev_record_button.setEnabled(False)
        self.next_record_button.setEnabled(False)

        self.worker = Worker(self.servers, query_type, query, start=1)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log_message.connect(self.log)
        self.worker.result_found.connect(self.display_result)
        self.worker.finished.connect(self.search_finished)

        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()

        self.toggle_search_buttons(False)  # Disable search buttons

    @staticmethod
    def validate_isbn(isbn):
        """Validates the ISBN using regex and checksum validation, treating lowercase 'x' as 'X' for usability."""
        isbn = (
            isbn.replace("-", "").replace(" ", "").upper()
        )  # Remove dashes, spaces, and convert to uppercase
        regex = re.compile(r"^(97[89])?\d{9}[\dX]$")  # Match ISBN-10 or ISBN-13

        if not regex.match(isbn):
            return False

        # Check ISBN-10
        if len(isbn) == 10:
            total = sum(
                (10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(isbn)
            )
            return total % 11 == 0

        # Check ISBN-13
        elif len(isbn) == 13:
            if 'X' in isbn:
                return False  # ISBN-13 should not contain 'X'
            total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(isbn))
            return total % 10 == 0

        return False

    def toggle_search_buttons(self, state):
        """Enable or disable search buttons."""
        self.search_isbn_button.setEnabled(state)
        self.search_title_author_button.setEnabled(state)
        self.cancel_button.setEnabled(not state)

    def cancel_search(self):
        """Cancel the ongoing search."""
        if self.worker:
            self.worker.cancel()

        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()

        self.progress_bar.setValue(0)  # Reset the progress bar
        self.toggle_search_buttons(True)
        self.log("Search cancelled.")

    def search_finished(self):
        """Handle the completion of a search."""
        self.toggle_search_buttons(True)

        # Only set the progress bar to 100% if the search was not cancelled
        if not self.worker.cancel_requested:
            self.progress_bar.setValue(100)
            self.log("Search completed.")
        else:
            self.progress_bar.setValue(0)  # Reset progress if search was cancelled

    def display_result(self, result):
        """Display search results."""
        summary = f"{result['summary']} - {result['number_of_hits']} hits"
        self.log(f"Displaying result from {summary}")

        item = QListWidgetItem(summary)
        item.setData(Qt.UserRole, result)
        self.results_window.addItem(item)

        self.total_records = result["number_of_hits"]
        self.current_record_index = 0
        self.current_marc_records = [
            result["raw_data"]
        ]  # Initialize the current record list

        self.update_navigation_buttons()

    def on_result_clicked(self, item):
        """Handle clicking on a search result."""
        result = item.data(Qt.UserRole)
        self.current_server_info = self.get_server_by_summary(result["summary"])
        raw_data = result["raw_data"]
        # Since we only deal with one record at a time, use extract_marc_record directly
        marc_record = self.extract_marc_record(raw_data)
        if marc_record:
            self.current_marc_records = [marc_record]  # Store as a single-record list
        self.total_records = result["number_of_hits"]
        self.current_record_index = 0
        self.display_current_record()
        self.next_record_button.setEnabled(
            self.total_records > 1 and not self.worker_thread.isRunning()
        )

    def get_server_by_summary(self, summary):
        """Helper function to retrieve server dictionary by its summary."""
        for server in self.servers:
            if f"{server['name']} ({server['host']}:{server['port']})" == summary:
                return server
        return None

    def display_current_record(self):
        """Display the current MARC record."""
        if self.current_marc_records and self.current_record_index < len(
            self.current_marc_records
        ):
            record = self.current_marc_records[self.current_record_index]
            formatted_record = []

            for field in record.fields:
                if field.is_control_field():
                    # For control fields (tags 001-009), just show the tag and data
                    formatted_record.append(f"{field.tag}    {field.data}")
                else:
                    # For data fields, show the tag, indicators, and subfields
                    indicators = "".join(field.indicators)  # Join the indicators
                    subfields = " ".join(
                        f"${sub.code} {sub.value}" for sub in field.subfields
                    )
                    formatted_record.append(f"{field.tag} {indicators} {subfields}")

            # Display the formatted record
            self.record_details_window.setPlainText("\n".join(formatted_record))
            self.download_button.setEnabled(True)
        else:
            self.record_details_window.setPlainText("No record available.")
            self.download_button.setEnabled(False)

        self.update_navigation_buttons()

    def update_navigation_buttons(self):
        """Enable or disable navigation buttons based on the current record index
        and search status."""
        # Enable only if there are more records and the search is not in progress
        if not self.worker_thread.isRunning():
            self.prev_record_button.setEnabled(self.current_record_index > 0)
            self.next_record_button.setEnabled(
                self.current_record_index < self.total_records - 1
            )
        else:
            self.prev_record_button.setEnabled(False)
            self.next_record_button.setEnabled(False)

    def show_next_record(self):
        """Navigate to the next record by running a new yaz-client to pull the next record."""
        server_name = None
        if self.current_record_index < self.total_records - 1:
            self.current_record_index += 1

            # Disable the "Next" button to prevent further clicks while fetching
            self.next_record_button.setEnabled(False)

            # If we haven't fetched the next record yet, perform a new YAZ query
            if self.current_record_index >= len(self.current_marc_records):
                start = self.current_record_index + 1  # The next record number to fetch

                try:
                    # Log contact with the server
                    self.log(f"Fetching next record {start} from server...")

                    # Rebuild the original search command based on query type
                    if self.current_query_type == "isbn":
                        search_command = (
                            f'find @attr 1=7 @attr 4=1 "{self.current_query}"\n'
                        )
                    elif self.current_query_type == "title_author":
                        title, author = self.current_query
                        search_command = (
                            f'find @and @attr 1=4 @attr 4=1 "{title}" '
                            f'@attr 1=1003 @attr 4=1 "{author}"\n'
                        )
                    else:
                        self.log("Unknown query type.")
                        return

                    # Append the show command to retrieve the next record
                    show_command = f"show {start}\n"
                    full_command = search_command + show_command

                    # Run the yaz-client command to fetch the next record
                    cmd = [
                        "yaz-client",
                        f'{self.current_server_info["host"]}:'
                        f'{self.current_server_info["port"]}/'
                        f'{self.current_server_info["database"]}',
                    ]

                    # Log the command for debugging purposes
                    server_name = self.current_server_info.get("name", "Unknown Server")
                    command_for_logging = full_command.replace("\n", " ")
                    self.log(
                        f"Connecting to {server_name} with "
                        f"command: {cmd} with {command_for_logging}"
                    )

                    # Use 'with' to ensure the subprocess is managed properly
                    with subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    ) as process:
                        self.process = (
                            process  # Assign the process for possible cancellation
                        )
                        stdout, _ = self.process.communicate(
                            full_command, timeout=self.timeout
                        )

                        # Clean YAZ output to extract only the MARC record data
                        cleaned_data = clean_yaz_output(stdout)

                        # Extract MARC record data from the cleaned output
                        marc_record = self.extract_marc_record(cleaned_data)

                        if "Present request out of range" in stdout:
                            self.log(
                                "Requested more records than available. No more records."
                            )
                            self.next_record_button.setEnabled(False)
                        elif marc_record:
                            # Append the new record to the list and display it
                            self.current_marc_records.append(marc_record)
                            self.display_current_record()
                        else:
                            self.log("Failed to extract MARC record.")
                            self.update_navigation_buttons()
                except subprocess.TimeoutExpired:
                    self.log(f"Connection to {server_name} timed out.")
                    self.update_navigation_buttons()
                except subprocess.CalledProcessError as e:
                    self.log(f"Subprocess error while querying {server_name}: {e}")
                    self.update_navigation_buttons()
                except OSError as e:
                    self.log(f"OS error while querying {server_name}: {e}")
                    self.update_navigation_buttons()
                except ValueError as e:
                    self.log(f"Error parsing data from {server_name}: {e}")
                    self.update_navigation_buttons()
                finally:
                    # Re-enable the "Next" button after the process completes
                    self.process = None

            else:
                # We've already fetched this record, so just display it
                self.log("Displaying previously fetched record.")
                self.display_current_record()

            self.update_navigation_buttons()
        else:
            self.log("No more records to display.")
            self.next_record_button.setEnabled(False)

    def show_prev_record(self):
        """Navigate to the previous record."""
        if self.current_record_index > 0:
            self.current_record_index -= 1
            self.display_current_record()
            self.log("Displaying previously fetched record.")

    def extract_marc_record(self, raw_data):
        """Extract a single MARC record from the raw data, handling malformed $$ fields."""
        try:
            record = Record()
            for line in raw_data.splitlines():
                if line[:3].isdigit() and line[3] == " ":
                    tag = line[:3]
                    if 10 <= int(tag) < 900:
                        indicators = line[4:6]

                        # Handle indicators properly (default to None if invalid)
                        if len(indicators) == 2:
                            indicators = [indicators[0], indicators[1]]
                        else:
                            indicators = (
                                None  # Set to None if not exactly two characters
                            )

                        line_content = line[7:]

                        # Check for the presence of $$ in the line content
                        while "$$" in line_content:
                            # Find the starting position of $$
                            start_pos = line_content.index("$$")
                            end_pos = line_content.find("$", start_pos + 2)

                            if end_pos == -1:
                                # No other $ found, log and remove everything after $$
                                removed_content = line_content[start_pos:]
                                line_content = line_content[:start_pos]
                                self.log(
                                    f"Malformed $$ detected, removed: '{removed_content}'"
                                )
                            else:
                                # Log and remove content from $$ to the next $
                                removed_content = line_content[start_pos:end_pos]
                                line_content = (
                                    line_content[:start_pos] + line_content[end_pos:]
                                )
                                self.log(
                                    f"Malformed $$ detected, removed: '{removed_content}'"
                                )

                        # Now split the sanitized line content into subfields
                        subfields = [
                            Subfield(code=part[0], value=part[1:].strip())
                            for part in line_content.split("$")[1:]
                        ]

                        # Create and add the field to the record
                        record.add_field(
                            Field(
                                tag=tag,
                                indicators=indicators,  # Properly handle indicators or set to None
                                subfields=subfields,
                            )
                        )
            return record
        except ValueError as e:
            self.log(f"Value error while extracting MARC record: {e}")
        except IndexError as e:
            self.log(f"Index error while extracting MARC record: {e}")
        except TypeError as e:
            self.log(f"Type error while extracting MARC record: {e}")
        return None

    def download_marc_record(self):
        """Download the currently displayed MARC record as a file."""
        if self.current_marc_records:
            record = self.current_marc_records[self.current_record_index]

            # Check if record is a proper pymarc Record object
            if isinstance(record, Record):
                author, title = get_record_info(record)
                default_filename = f"{author}_{title}".replace(" ", "_")

                file_name, _ = QFileDialog.getSaveFileName(
                    self, "Save MARC Record", default_filename, "MARC Files (*.mrc)"
                )
                if file_name:
                    with open(file_name, "wb") as file:
                        file.write(record.as_marc())
                    QMessageBox.information(
                        self, "Success", "MARC record saved successfully!"
                    )
            else:
                QMessageBox.warning(self, "Error", "Invalid MARC record format.")
        else:
            QMessageBox.warning(self, "Error", "No MARC record to save.")

    def closeEvent(self, event):
        """Ensure the worker thread and subprocesses are properly
        terminated when the application is closed."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.log("Closing & cleaning up workers...")
            self.worker.cancel()  # Signal the worker to stop
            self.worker_thread.quit()  # Terminate the thread
            self.worker_thread.wait()  # Wait for it to finish

        # If you have any subprocesses still running, ensure they are terminated
        if hasattr(self.worker, "process") and self.worker.process:
            self.log("Closing & cleaning up subprocesses...")
            self.worker.process.terminate()  # Terminate the process
            self.worker.process.wait()  # Wait for process termination

        # Clear memory and force garbage collection
        self.current_marc_records.clear()
        gc.collect()

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = Z3950SearchApp()
    ex.show()
    sys.exit(app.exec_())
