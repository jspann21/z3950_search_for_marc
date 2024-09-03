import sys
import subprocess
import json
import re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextEdit, QLabel, QProgressBar,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
from pymarc import Record, Field, Subfield


class Worker(QObject):
    """Worker class for handling Z39.50 searches in a separate thread."""
    finished = pyqtSignal()
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_found = pyqtSignal(dict)

    def __init__(self, servers, query_type, query, timeout=60, start=1, num_records=3):
        """Initialize the worker with the given parameters."""
        super().__init__()
        self.servers = servers
        self.query_type = query_type
        self.query = query
        self.timeout = timeout  # Timeout for each server connection
        self.start = start  # Start position for record retrieval
        self.num_records = num_records  # Number of records to retrieve
        self.process = None
        self.servers_processed = 0
        self.cancel_requested = False  # Flag to track cancellation

    def run(self):
        """Main loop for querying servers."""
        total_servers = len(self.servers)
        if total_servers == 0:  # Prevent division by zero
            self.finished.emit()
            return
        self.log_message.emit(f"Total servers to query: {total_servers}")

        for server in self.servers:
            if self.cancel_requested:
                self.log_message.emit("Search cancelled.")
                break
            if not isinstance(server, dict):
                self.log_message.emit(f"Error: Invalid server information provided: {server}")
                continue

            server_name = server.get('name', 'Unknown Server')
            server_host = server.get('host', 'Unknown Host')
            try:
                self.log_message.emit(
                    f"Connecting to {server_name} at {server_host}:"
                    f"{server.get('port', 'Unknown Port')}..."
                )
                self.run_yaz_client(server, self.query_type, self.query)
            except subprocess.TimeoutExpired:
                self.log_message.emit(
                    f"Connection to {server_name} timed out.\n"
                    f"Details: Timeout after {self.timeout} seconds."
                )
            except Exception as e:
                self.log_message.emit(f"Error querying {server_name}: {e}")

            # Increment the number of servers processed
            self.servers_processed += 1

            # Calculate the progress
            progress = int((self.servers_processed / total_servers) * 100)

            # Emit the progress to update the progress bar
            self.progress.emit(progress)

        # Ensure the progress bar reaches 100% upon completion
        if not self.cancel_requested:
            self.progress.emit(100)
        self.finished.emit()

    def run_yaz_client(self, server, query_type, query):
        """Run the YAZ client to query the server."""
        try:
            # Validate server data
            server_name = server.get('name', 'Unknown Server')
            server_host = server.get('host', 'Unknown Host')
            server_port = server.get('port', 'Unknown Port')

            if (server_name == 'Unknown Server' or server_host == 'Unknown Host' or
                    server_port == 'Unknown Port'):
                self.log_message.emit(f"Invalid server configuration: {server}")
                return

            yaz_client_path = 'C:\\Program Files\\YAZ\\bin\\yaz-client.exe'
            if query_type == 'isbn':
                use_attr = '7'
                search_command = (
                    f'find @attr 1={use_attr} @attr 4=1 "{query}"\n'
                    f'show {self.start}+{self.num_records}\n'
                )
            elif query_type == 'title_author':
                use_attr_title = '4'
                use_attr_author = '1003'
                title, author = query
                search_command = (
                    f'find @and @attr 1={use_attr_title} @attr 4=1 "{title}" '
                    f'@attr 1={use_attr_author} @attr 4=1 "{author}"\n'
                    f'show {self.start}+{self.num_records}\n'
                )
            else:
                self.log_message.emit(f"Unknown query type for {server['name']}.")
                return

            cmd = [
                yaz_client_path,
                f'{server["host"]}:{server["port"]}/{server["database"]}',
            ]

            self.log_message.emit(f"Executing command: {cmd} with query: {search_command.strip()}")

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',  # Specify utf-8 encoding here
                errors='replace'  # Replace characters that can't be decoded
            )

            stdout, stderr = self.process.communicate(search_command, timeout=self.timeout)

            if self.cancel_requested:
                self.process.terminate()
                return

            if self.process.returncode == 0 and stdout.strip():
                if "Number of hits:" in stdout:
                    # Extract the number of hits
                    hits_line = next(
                        (line for line in stdout.splitlines() if "Number of hits:" in line),
                        None
                    )
                    number_of_hits = (
                        int(hits_line.split(":")[1].split(",")[0].strip())
                        if hits_line else 0
                    )

                    # Emit result if records are found
                    if number_of_hits > 0:
                        result = {
                            'summary': f"{server['name']} ({server['host']}:{server['port']})",
                            'raw_data': stdout.strip(),
                            'number_of_hits': number_of_hits
                        }
                        self.result_found.emit(result)
                    else:
                        self.log_message.emit(f"No records found in {server['name']}.")
                else:
                    self.log_message.emit(f"No hits information found in {server['name']}.")
            else:
                self.log_message.emit(f"No records found in {server['name']}.")
        except subprocess.TimeoutExpired as e:
            self.log_message.emit(f"Connection to {server['name']} timed out.\nDetails: {str(e)}")
        except Exception as e:
            self.log_message.emit(f"An error occurred while querying {server['name']}: {e}")

    def cancel(self):
        """Method to be called when cancel is requested."""
        self.cancel_requested = True
        if self.process and self.process.poll() is None:
            self.process.terminate()


class Z3950SearchApp(QWidget):
    """Main application class for the Z39.50 MARC Record Search."""
    def __init__(self):
        """Initialize the application and UI."""
        super().__init__()
        self.initUI()
        self.load_servers()
        self.worker_thread = None
        self.current_marc_records = []
        self.current_record_index = 0
        self.total_records = 0
        self.current_server_info = None  # Store the current server info
        self.current_query_type = None  # Store the current query type
        self.current_query = None  # Store the current query

    def initUI(self):
        """Initialize the user interface."""
        self.setWindowTitle('Z39.50 MARC Record Search')
        self.setGeometry(100, 100, 800, 600)
        main_layout = QVBoxLayout()

        # ISBN Search Box
        isbn_group = QGroupBox("Search by ISBN")
        isbn_layout = QVBoxLayout()
        self.isbn_input = QLineEdit(self)
        self.isbn_input.setPlaceholderText("ISBN")
        self.search_isbn_button = QPushButton('Search ISBN', self)
        self.search_isbn_button.clicked.connect(self.start_isbn_search)
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
        self.search_title_author_button = QPushButton('Search Title && Author', self)
        self.search_title_author_button.clicked.connect(self.start_title_author_search)
        title_author_layout.addWidget(self.title_input)
        title_author_layout.addWidget(self.author_input)
        title_author_layout.addWidget(self.search_title_author_button)
        title_author_group.setLayout(title_author_layout)

        # Cancel Button
        self.cancel_button = QPushButton('Cancel', self)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setFixedHeight(60)
        self.cancel_button.clicked.connect(self.cancel_search)

        # Arrange the top layout
        top_layout = QHBoxLayout()
        top_layout.addWidget(isbn_group)
        top_layout.addWidget(title_author_group)
        top_layout.addWidget(self.cancel_button)

        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0, 100)  # Ensure the range is 0 to 100

        # Results window
        self.results_window = QListWidget(self)
        self.results_window.itemClicked.connect(self.on_result_clicked)

        # Record Details window
        self.record_details_window = QTextEdit(self)
        self.record_details_window.setReadOnly(True)

        # Log window
        self.log_window = QTextEdit(self)
        self.log_window.setReadOnly(True)
        self.log_window.setMaximumHeight(150)  # Set shorter height for the log window

        # Download button
        self.download_button = QPushButton('Download Record', self)
        self.download_button.setEnabled(False)  # Initially disabled
        self.download_button.clicked.connect(self.download_marc_record)

        # Navigation Buttons
        self.prev_record_button = QPushButton('Previous Record', self)
        self.prev_record_button.setEnabled(False)
        self.prev_record_button.clicked.connect(self.show_prev_record)

        self.next_record_button = QPushButton('Next Record', self)
        self.next_record_button.setEnabled(False)
        self.next_record_button.clicked.connect(self.show_next_record)

        self.load_more_button = QPushButton('Load More Records', self)
        self.load_more_button.setEnabled(False)
        self.load_more_button.clicked.connect(self.load_more_records)

        nav_layout = QHBoxLayout()
        nav_layout.addWidget(self.prev_record_button)
        nav_layout.addWidget(self.next_record_button)
        nav_layout.addWidget(self.load_more_button)

        # Add widgets to the main layout
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
            with open('servers.json', 'r') as f:
                self.servers = json.load(f)
            self.log(f"Loaded {len(self.servers)} servers from 'servers.json'.")
        except json.JSONDecodeError as e:
            self.servers = []
            self.log(f"Failed to load servers from 'servers.json': {e}")
        except Exception as e:
            self.servers = []
            self.log(f"An unexpected error occurred while loading servers: {e}")

    def log(self, message):
        """Log messages to the log window."""
        self.log_window.append(message)
        self.log_window.ensureCursorVisible()

    def update_progress(self, value):
        """Update the progress bar with the given value."""
        if isinstance(value, int):
            self.progress_bar.setValue(value)

    def handle_log_message(self, message):
        """Handle log messages emitted by the worker."""
        self.log(message)

    def start_isbn_search(self):
        """Start a search by ISBN."""
        isbn = self.isbn_input.text().strip()
        if not isbn:
            self.log("Please enter an ISBN.")
            return
        self.start_search('isbn', isbn)

    def start_title_author_search(self):
        """Start a search by title and author."""
        title = self.title_input.text().strip()
        author = self.author_input.text().strip()
        if not title or not author:
            self.log("Please enter both a title and an author.")
            return
        self.start_search('title_author', (title, author))

    def start_search(self, query_type, query):
        """Start a search based on the query type and query provided."""
        self.log(f"Starting {query_type} search with query: {query}")
        self.progress_bar.setValue(0)
        self.results_window.clear()

        # Reset the state for a new search
        self.current_marc_records = []
        self.current_record_index = 0
        self.total_records = 0
        self.record_details_window.clear()

        # Reset navigation buttons
        self.prev_record_button.setEnabled(False)
        self.next_record_button.setEnabled(False)
        self.load_more_button.setEnabled(False)

        self.current_query_type = query_type
        self.current_query = query

        self.worker = Worker(self.servers, query_type, query, timeout=10)
        self.worker.progress.connect(self.update_progress)
        self.worker.log_message.connect(self.handle_log_message)
        self.worker.result_found.connect(self.display_result)
        self.worker.finished.connect(self.search_finished)

        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()

        self.search_isbn_button.setEnabled(False)
        self.search_title_author_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def cancel_search(self):
        """Cancel the ongoing search, reset the progress bar, and reset the UI."""
        if self.worker:
            self.worker.cancel()  # Signal the worker to stop the operation

        if self.worker_thread:
            self.worker_thread.quit()  # Gracefully exit the thread's event loop
            self.worker_thread.wait()  # Block until the thread has finished

        # Reset the progress bar and log the cancellation
        self.progress_bar.setValue(0)
        self.log("Search cancelled.")

        # Reset the UI state
        self.search_isbn_button.setEnabled(True)
        self.search_title_author_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

        # Clean up the worker and thread references
        self.worker_thread = None
        self.worker = None

    def search_finished(self):
        """Handle the completion of a search or cancellation."""
        self.log("Search completed.")
        self.search_isbn_button.setEnabled(True)
        self.search_title_author_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(100)

        if self.worker_thread:
            self.worker_thread.quit()  # Gracefully exit the thread's event loop
            self.worker_thread.wait()  # Block until the thread has finished
            self.worker_thread = None

        self.worker = None  # Clean up the worker reference

    def display_result(self, result):
        """Display search results in the results window."""
        summary = f"{result['summary']} - {result['number_of_hits']} hits"
        self.log(f"Displaying result from {summary}")

        # Add the summary to the results window
        item = QListWidgetItem(summary)
        item.setData(Qt.UserRole, result)  # Store the entire result dictionary
        self.results_window.addItem(item)

        # Set the total number of records
        self.total_records = result['number_of_hits']

        # Reset record display and buttons
        if self.current_marc_records:
            self.display_current_record()
        else:
            self.record_details_window.clear()
            self.prev_record_button.setEnabled(False)
            self.next_record_button.setEnabled(False)
            self.load_more_button.setEnabled(False)

    def on_result_clicked(self, item):
        """Handle clicking on a search result and display the initial records."""
        # Reset the state and clear previous records
        self.current_marc_records = []
        self.current_record_index = 0
        self.record_details_window.clear()

        # Reset navigation buttons
        self.prev_record_button.setEnabled(False)
        self.next_record_button.setEnabled(False)
        self.load_more_button.setEnabled(False)

        result = item.data(Qt.UserRole)  # Get the result dictionary
        raw_data = result['raw_data']  # Extract the raw_data from the result dictionary

        # Extract the server name more robustly
        summary = result['summary']
        server_name_fragment = summary.split('(')[0].strip().lower()  # Extract and lowercase

        # Perform a case-insensitive match to find the correct server
        server_info = next(
            (server for server in self.servers if server_name_fragment in server['name'].lower()),
            None
        )

        if server_info:
            self.current_server_info = server_info  # Store the full server info
            self.current_server_info['raw_data'] = raw_data  # Attach the raw data to the server info

            # Load and display the first set of records
            self.current_marc_records = self.extract_marc_records(raw_data)
            self.current_record_index = 0
            self.display_current_record()

            # Update navigation buttons based on the loaded records
            self.update_navigation_buttons()
        else:
            self.log(f"Error: Server information for {server_name_fragment} not found.")

    def display_current_record(self):
        """Display the current MARC record based on the current_record_index."""
        if 0 <= self.current_record_index < len(self.current_marc_records):
            marc_record = self.current_marc_records[self.current_record_index]
            formatted_record = []

            for field in marc_record.fields:
                if field.is_control_field():
                    formatted_record.append(f"{field.tag}    {field.data}")
                else:
                    subfields = ' '.join(
                        [f"${sub.code} {sub.value}" for sub in field.subfields]
                    )
                    formatted_record.append(
                        f"{field.tag} {''.join(field.indicators)} {subfields}"
                    )

            self.record_details_window.setPlainText('\n'.join(formatted_record))
            self.download_button.setEnabled(True)  # Enable download button for a valid record
        else:
            self.record_details_window.setPlainText("No record available.")
            self.download_button.setEnabled(False)  # Disable download button if no record is displayed

        # Update the state of navigation buttons
        self.update_navigation_buttons()

    def update_record_details(self):
        """Update the record details window with the current MARC record."""
        if not self.current_marc_records or self.current_record_index >= len(self.current_marc_records):
            self.record_details_window.setPlainText("No more records available.")
            self.download_button.setEnabled(False)
            return

        marc_record = self.current_marc_records[self.current_record_index]

        formatted_record = []
        for field in marc_record.fields:
            if field.is_control_field():
                formatted_record.append(f"{field.tag}    {field.data}")
            else:
                subfields = ' '.join([f"${sub.code} {sub.value}" for sub in field.subfields])
                formatted_record.append(f"{field.tag} {''.join(field.indicators)} {subfields}")

        self.record_details_window.setPlainText('\n'.join(formatted_record))
        self.download_button.setEnabled(True)

        # Manage navigation buttons
        self.prev_record_button.setEnabled(self.current_record_index > 0)
        self.next_record_button.setEnabled(self.current_record_index < len(self.current_marc_records) - 1)

        # Enable load more button one record earlier
        if self.current_record_index == len(self.current_marc_records) - 2:
            if len(self.current_marc_records) < self.total_records:
                self.load_more_button.setEnabled(True)
            else:
                self.load_more_button.setEnabled(False)

    def load_more_records(self):
        """Load more records starting from the next record after the current set."""
        start_position = len(self.current_marc_records) + 1

        self.worker = Worker(
            [self.current_server_info],
            self.current_query_type,
            self.current_query,
            start=start_position,
            num_records=3,
            timeout=10
        )

        self.worker.progress.connect(self.update_progress)
        self.worker.log_message.connect(self.handle_log_message)
        self.worker.result_found.connect(self.append_more_records)
        self.worker.finished.connect(self.search_finished)

        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()

        # Temporarily disable navigation buttons to avoid issues during loading
        self.prev_record_button.setEnabled(False)
        self.next_record_button.setEnabled(False)
        self.load_more_button.setEnabled(False)

    def append_more_records(self, result):
        """Append newly loaded records to the current list and update UI."""
        new_records = self.extract_marc_records(result['raw_data'])

        if new_records:
            previous_length = len(self.current_marc_records)
            self.current_marc_records.extend(new_records)
            self.current_record_index = previous_length  # Move to the first of the newly loaded records
            self.display_current_record()
        else:
            self.log("No new records were retrieved.")

        self.update_navigation_buttons()

    def update_navigation_buttons(self):
        """Enable or disable navigation buttons based on the current state."""
        self.prev_record_button.setEnabled(self.current_record_index > 0)
        self.next_record_button.setEnabled(self.current_record_index < len(self.current_marc_records) - 1)
        self.load_more_button.setEnabled(
            len(self.current_marc_records) < self.total_records and
            self.current_record_index == len(self.current_marc_records) - 1
        )

    def show_next_record(self):
        """Navigate to the next record."""
        if self.current_record_index < len(self.current_marc_records) - 1:
            self.current_record_index += 1
            self.display_current_record()

    def show_prev_record(self):
        """Navigate to the previous record."""
        if self.current_record_index > 0:
            self.current_record_index -= 1
            self.display_current_record()

    def extract_marc_records(self, raw_data):
        """Extract MARC records from the raw data."""
        records = []
        record_blocks = raw_data.strip().split('\n\n')
        for block in record_blocks:
            record = self.extract_marc_record(block)
            if record and record.fields:  # Only append if the record is valid and contains fields
                records.append(record)
        return records

    def extract_marc_record(self, raw_data):
        """Extract a single MARC record from the raw data."""
        try:
            record = Record()
            lines = raw_data.strip().split('\n')

            for line in lines:
                tag = line[:3]

                # Ignore lines that do not start with a valid three-digit tag followed by a space
                if not (tag.isdigit() and line[3] == ' '):
                    continue

                # Convert tag to an integer for comparison
                tag_int = int(tag)

                # Ignore control fields (000-009) and tags 900 or greater
                if tag_int < 10 or tag_int >= 900:
                    continue

                # Data fields (010-899) have indicators and subfields
                indicators = line[4:6]
                subfield_data = line[7:].strip()
                subfields = []
                parts = subfield_data.split('$')[1:]  # Split on '$' and ignore the first empty part

                for part in parts:
                    code = part[0]
                    data = part[1:].strip()
                    subfields.append(Subfield(code=code, value=data))

                # Add the field to the record with correct indicators and subfields
                record.add_field(Field(tag=tag, indicators=list(indicators), subfields=subfields))

            return record

        except Exception as e:
            self.log(f"Failed to extract MARC record: {e}")
            return None

    def download_marc_record(self):
        """Download the currently displayed MARC record as a file."""
        if hasattr(self, 'current_marc_records') and self.current_marc_records:
            marc_record = self.current_marc_records[self.current_record_index]

            author = title = "MARC_Record"
            for field in marc_record.get_fields('100', '110', '111', '245'):
                if field.tag.startswith('1'):  # Author fields
                    author = re.sub(r'[^\w\s]', '', field['a']).strip()
                if field.tag == '245':  # Title field
                    title = re.sub(r'[^\w\s]', '', field['a']).strip()

            default_filename = f"{author}_{title}".replace(" ", "_")

            options = QFileDialog.Options()
            file_name, _ = QFileDialog.getSaveFileName(
                self, "Save MARC Record", default_filename,
                "MARC Files (*.mrc);;All Files (*)", options=options
            )
            if file_name:
                with open(file_name, 'wb') as file:
                    file.write(marc_record.as_marc())
                QMessageBox.information(self, "Success", "MARC record saved successfully!")
        else:
            QMessageBox.warning(self, "Error", "No MARC record to save.")

    def closeEvent(self, event):
        """Ensure the worker thread is properly terminated when the application is closed."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker.cancel()
            self.worker_thread.quit()
            self.worker_thread.wait()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = Z3950SearchApp()
    ex.show()
    sys.exit(app.exec_())
