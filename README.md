# Z39.50 MARC Record Search Application

This repository contains a PyQt5-based graphical user interface (GUI) application designed to perform **Z39.50** searches across multiple servers to retrieve **MARC** records. The application supports searches by **ISBN**, **Title**, and **Author**, filters servers based on location (**USA** or **Worldwide**), and displays the retrieved MARC records in a user-friendly format.

## Table of Contents
- [Features](#features)
- [How It Works](#how-it-works)
  - [Main Application: `main.py`](#main-application-mainpy)
    - [Running a Search](#running-a-search)
    - [Handling Results and Navigation](#handling-results-and-navigation)
    - [Dynamic Record Fetching](#dynamic-record-fetching)
    - [Error Handling and Logs](#error-handling-and-logs)
    - [Location Filtering](#location-filtering)
- [Configuration: `servers.json`](#configuration-serversjson)
- [Installation](#installation)
- [Usage](#usage)
- [Contributing](#contributing)

## Features

- **Search Functionality**:
  - Search by **ISBN**.
  - Search by a combination of **Title** and **Author**.
  
- **Location-Based Server Filtering**:
  - **USA**: Includes servers based in the United States.
  - **Worldwide**: Includes servers from around the globe.
  - Users can select one or both locations to filter the servers used in the search.
  
- **Concurrent Server Queries**:
  - Communicates with multiple **Z39.50 servers** concurrently.
  - Prioritizes the **Library of Congress (LOC)** in the search sequence.

- **MARC Record Management**:
  - Displays retrieved **MARC** records in a formatted view.
  - Provides navigation between records with **Next** and **Previous** buttons.
  - **Download MARC records** to a file in `.mrc` format.
  
- **User Experience Enhancements**:
  - **Progress Bar**: Shows the progress of ongoing search operations.
  - **Logging**: Comprehensive logs within the application for monitoring operations and debugging.
  - **Cancel Mechanism**: Allows users to stop long-running searches gracefully.
  - **Dynamic Record Fetching**: Fetches additional records on-demand to reduce memory usage.

## How It Works

### Main Application: `main.py`

The **Z39.50 MARC Record Search** application is the main graphical interface for users to search and retrieve **MARC records** from configured Z39.50 servers.

#### Running a Search

1. **Entering a Search Query**:
   - You can search by entering an **ISBN** or a **Title** and **Author**.
   - After entering the desired search terms, click the corresponding search button to initiate the search.

      ![image](https://github.com/user-attachments/assets/6c4c0307-8a7f-45d4-9c5a-5f7a4399d208)




2. **Running the Search**:
   - The application constructs a query command using the **YAZ client** to communicate with Z39.50 servers.
   - The search query is formatted based on the search type (ISBN or Title/Author) and sent to the servers configured in the `servers.json` file. **LOC** is queried first.
   - A **progress bar** shows the progress of the search.

3. **Displaying Search Results**:
   - If the server returns a valid response, the application processes the returned data.
   - **Number of Hits**: Displays the number of records matching the query from each server.
   - The search results window shows summaries of each server response, including the **number of hits** returned by each server.

     ![image](https://github.com/user-attachments/assets/2468adea-41a5-4d7a-ac2e-2ab2e26b8e25)


#### Handling Results and Navigation

1. **Clicking on Search Results**:
   - After a search completes, you can click on any result in the list to view more details about the records returned.
   - Initially, only the first record is retrieved. The remaining records are fetched dynamically when requested.

2. **Navigating Between Results**:
   - You can use the **Next Record** and **Previous Record** buttons to navigate through records.
   - As you navigate, the application dynamically fetches additional records from the server, improving performance by fetching only what’s needed.
   - For each record, the MARC fields are parsed and displayed in a human-readable format in the details window. Control fields (tags `001-009`) and data fields (tags `900+`) are discarded because they were found to contain unnecessary or non-essential information.

     **Note**: MARC record fields `000-009` and `900+` are excluded because they often contain metadata or control information that is not useful for this application’s purposes.

     ![image](https://github.com/user-attachments/assets/0405cb9e-093c-4196-959b-da49c6a7f6f8)


3. **Downloading Records**:
   - After viewing a record, you can **download the MARC record** by clicking the **Download Record** button.
   - The record will be saved in `.mrc` format, which is compatible with many MARC record processing systems.

   **Recreating MARC Records with `pymarc`**:
   - The application uses the **`pymarc`** library to parse, process, and display MARC records.
   - After retrieving the raw data from the Z39.50 server, the application uses `pymarc` to recreate a new MARC record object. Only the relevant fields (tags `010-899`) are included in this object.
   - The new MARC record can then be saved to a file in `.mrc` format, allowing the user to easily share or archive the record.
   
#### Dynamic Record Fetching

The application fetches records on-demand:
- When you request the next record, the application queries the server dynamically rather than fetching all records at once.
- This feature improves memory usage and performance, especially with large result sets.

#### Error Handling and Logs

- Errors like missing server keys, invalid MARC data, or connection issues are logged in the application's **log window**.
- You can track **search progress** and see details about the queries being run against Z39.50 servers.

#### Location Filtering

The **Location Filtering** feature allows users to filter the Z39.50 servers based on their geographic location, enhancing search relevance and performance.

1. **Location Selection**:
   - **USA**: Includes servers based in the United States.
   - **Worldwide**: Includes servers from around the globe.
   - Users can select one or both options to include the desired set of servers in their search.

2. **Impact on Server Selection**:
   - When a search is initiated, the application filters the servers listed in `servers.json` based on the selected locations.
   - Only servers that match the selected locations are queried, reducing unnecessary network requests and focusing the search on relevant servers.

3. **Default Settings**:
   - Both **USA** and **Worldwide** filters are checked by default, allowing searches across all available servers.
   - Users can uncheck either option to limit the search scope as needed.

4. **Configuration Dependence**:
   - Each server entry in `servers.json` must include a `"location"` field specifying its geographic category (`"USA"` or `"Worldwide"`).
   - Proper configuration ensures that the filtering works correctly during searches.


### Configuration: `servers.json`

The **`servers.json`** file contains a list of Z39.50 servers used by the application for querying MARC records. If you find new server data or validate existing servers, update this file with the correct configurations.

Example `servers.json` structure:

```json
[
  {
    "name": "Library of Congress",
    "host": "z3950.loc.gov",
    "port": 7090,
    "database": "VOYAGER",
    "location": "USA"
  },
  {
    "name": "British Library",
    "host": "z3950.bl.uk",
    "port": 210,
    "database": "UKPD",
    "location": "Worldwide"
  }
  // Add more server entries here...
]
```

### Fields Explained:

- **name**: The name of the Z39.50 server.
- **host**: The hostname or IP address of the server.
- **port**: The port number on which the server listens for Z39.50 requests.
- **database**: The specific database to query on the server.
- **location**: The geographic category of the server (`"USA"` or `"Worldwide"`).

## Installation

1. Clone the repository from GitHub:

    ```bash
    git clone https://github.com/jspann21/z3950_search_for_marc.git
    cd z3950_search_for_marc
    ```

2. Install the required dependencies:

    ```bash
    pip install -r requirements.txt
    ```

3. Ensure the **YAZ client** is installed and available in your system's PATH. You can find instructions and download links here: [YAZ Client by IndexData](https://www.indexdata.com/resources/software/yaz/).

4. Ensure the `servers.json` file containing z39.50 server information is located with the scripts.


## Usage

To run the application:

```bash
python main.py
```

The graphical user interface will open, allowing you to:

1. **Search by ISBN** or **Title/Author**:
   - Enter the ISBN in the ISBN search box or enter the Title and Author in the respective fields.
   - Select the desired locations (**USA**, **Worldwide**, or both) to filter the servers used in the search.
   - Click the corresponding search button to initiate the search.

2. **View Results** and **Navigate** through records:
   - Search results will display summaries of each server's response.
   - Click on a result to view detailed MARC record information.
   - Use the **Next** and **Previous** buttons to navigate through records.

3. **Download MARC Records**:
   - After viewing a record, click the **Download Record** button to save the MARC record in `.mrc` format.

4. **Monitor Progress and Logs**:
   - The **progress bar** shows the search progress.
   - The **log window** displays detailed logs for operations and debugging.

5. **Cancel Searches**:
   - Click the **Cancel** button to stop ongoing searches gracefully.

## Contributing

If you find any issues or have suggestions for improvement, feel free to open a pull request or file an issue on GitHub. Contributions are welcome!


