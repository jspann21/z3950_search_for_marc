# Z39.50 MARC Record Search Application

This repository contains a PyQt5-based graphical user interface (GUI) application designed to perform **Z39.50** searches across multiple servers to retrieve **MARC** records. The application supports searches by **ISBN**, **Title**, and **Author** and displays the retrieved MARC records in a user-friendly format.

## Table of Contents
- [Features](#features)
- [How It Works](#how-it-works)
  - [Main Application: `z3950search.py`](#main-application-z3950searchpy)
    - [Running a Search](#running-a-search)
    - [Handling Results and Navigation](#handling-results-and-navigation)
- [Supporting Scripts](#supporting-scripts)
  - [`retrieve_loc_z3950_servers.py`](#retrieve_loc_z3950_serverspy)
  - [`test_loc_z3950_servers.py`](#test_loc_z3950_serverspy)
- [Configuration: `servers.json`](#configuration-serversjson)
- [Installation](#installation)
- [Usage](#usage)
- [Contributing](#contributing)

## Features

- Search by **ISBN** or by a combination of **Title** and **Author**.
- Communicates with multiple **Z39.50 servers** concurrently, including the **Library of Congress (LOC)**, which is prioritized in the search.
- Displays retrieved **MARC** records in a formatted view and provides navigation between records.
- **Download MARC records** to a file in `.mrc` format.
- Displays **search progress** and logs for user feedback.
- Provides a **cancel mechanism** to stop long-running searches.
- Dynamically fetches **additional records** when navigating through multiple results, reducing memory usage.
- Includes two supporting scripts:
  - **retrieve_loc_z3950_servers.py**: Retrieves Z39.50 server information from the Library of Congress website.
  - **test_loc_z3950_servers.py**: Tests the connectivity of Z39.50 servers and verifies that they do not require authentication. The results can be used to populate `servers.json`.

## How It Works

### Main Application: `z3950search.py`

The **Z39.50 MARC Record Search** application is the main graphical interface for users to search and retrieve **MARC records** from configured Z39.50 servers.

#### Running a Search

1. **Entering a Search Query**:
   - You can search by entering an **ISBN** or a **Title** and **Author**.
   - After entering the desired search terms, click the corresponding search button to initiate the search.

      ![image](https://github.com/user-attachments/assets/e755485c-2235-4bcf-b55f-5f7b27363df8)




2. **Running the Search**:
   - When a search is initiated, the application constructs a query command compatible with the **YAZ client**. YAZ (Z39.50 toolkit) is a crucial component that handles communication with Z39.50 servers.
   - The query is formatted based on the type of search (e.g., ISBN or Title/Author). It sends the query to each configured server in `servers.json`, with **LOC** being the first server queried.
   - The command runs through the **YAZ client** using the subprocess module, sending the query and waiting for a response from the server.
   - Progress is displayed in the **progress bar** at the top of the window.

3. **Displaying Search Results**:
   - If the server returns a valid response, the application processes the returned data.
   - **Number of hits**: If multiple records are found, the server response includes a "Number of Hits" line, which indicates how many records match the query. This is displayed in the results window.
   - The search results window will show summaries of each server response, including the **number of hits** returned by each server.

     ![image](https://github.com/user-attachments/assets/dcae2e5b-5aa3-4f4b-a9d2-0ba0be868d83)


#### Handling Results and Navigation

1. **Clicking on Search Results**:
   - After a search is complete, you can click on any result in the list to view more details about the records returned by that server.
   - Initially, only the first record from the server is retrieved. The rest of the records are **fetched dynamically** when requested.
   
2. **Navigating Between Results**:
   - You can navigate between the records using the **Next Record** and **Previous Record** buttons.
   - When navigating, instead of loading all the records at once, the application sends a new **YAZ client** command to retrieve the next record from the server. This **on-demand record retrieval** improves memory usage and performance by fetching records only as needed.
   - For each record, the MARC fields are parsed and displayed in a human-readable format in the details window. Control fields (tags `001-009`) and data fields (tags `900+`) are discarded because they were found to contain unnecessary or non-essential information.

     **Note**: MARC record fields `000-009` and `900+` are excluded because they often contain metadata or control information that is not useful for this application’s purposes.

     ![image](https://github.com/user-attachments/assets/6dfef584-caf1-4fc2-9c02-366b79a5b4ee)


3. **Downloading Records**:
   - After viewing a record, you can **download the MARC record** by clicking the **Download Record** button.
   - The record will be saved in `.mrc` format, which is compatible with many MARC record processing systems.

   **Recreating MARC Records with `pymarc`**:
   - The application uses the **`pymarc`** library to parse, process, and display MARC records.
   - After retrieving the raw data from the Z39.50 server, the application uses `pymarc` to recreate a new MARC record object. Only the relevant fields (tags `010-899`) are included in this object.
   - The new MARC record can then be saved to a file in `.mrc` format, allowing the user to easily share or archive the record.

### Supporting Scripts

#### `retrieve_loc_z3950_servers.py`

This script is designed to pull Z39.50 server information from the Library of Congress (LOC) website. It scrapes the server list provided on the LOC's public resources and compiles the data into a format that can be used in the `servers.json` file for the Z39.50 search tool.

The process flow of the script is as follows:

1. **Scraping the LOC Website**: 
   The script makes a request to the LOC website that contains a list of Z39.50 servers and parses the HTML response using the `BeautifulSoup` library to extract server data, including hostnames, ports, and database names.
   
2. **Formatting the Server Data**:
   After scraping, the server data is structured into a list of dictionaries. Each dictionary contains important details like the server name, host, port, and database. These details are essential for establishing connections with Z39.50 servers.

3. **Writing to `loc_servers.json`**:
   The extracted server information is written to a file named `loc_servers.json`, which can be renamed `servers.json` to be used by the main `z3950search` application to query Z39.50 servers for MARC records.

##### Example Usage:

- The script sends a request to the LOC's server information page and uses `BeautifulSoup` to parse the server details.
- The results are saved in a `loc_servers.json` file. The `test_loc_z3950_servers.py` script will read the `loc_servers.json` file to determine which servers are available and open. These two scripts could have been combined, but they're not.

This script simplifies the process of obtaining and updating the Z39.50 server list from the LOC, ensuring that your `servers.json` file is always up to date with the latest publicly available Z39.50 servers.


#### `test_loc_z3950_servers.py`

This script is used to test the connectivity of each Z39.50 server retrieved by `retrieve_loc_z3950_servers.py`. It ensures that the servers are available and do not require authentication (since some Z39.50 servers are restricted and may not be publicly accessible). 

The process flow is as follows:

1. **Testing the Connection**: 
   Each server from the list `loc_servers.json` is tested using the `yaz-client` command to ensure that the server can be reached.
   
2. **Authentication Check**:
   It verifies whether the server requires authentication. Only servers that do not require authentication are written to `non_auth_loc_servers.json` for consideration.

3. **Writing Reachable Servers to File**:
   The script writes the servers that successfully pass the connection and authentication test to a new file. This ensures that only servers that can be queried without issues are included in the final `non_auth_loc_servers.json` file.

These servers can be copied to `servers.json` to ensure the file contains a list of functional and publicly accessible Z39.50 servers.

##### Example Usage:

- The script will iterate through each server in `loc_servers.json` generated by `retrieve_loc_z3950_servers.py` and attempt to connect.
- Any servers that are reachable and do not require authentication are written to a new file.
  


### Configuration: `servers.json`

The **`servers.json`** file contains a list of server configurations used by the application to query MARC records. If you retrieve new server data or validate existing servers, update this file with the correct configurations.

#### Example `servers.json` structure:

```json
[
  {
    "name": "Library of Congress",
    "host": "z3950.loc.gov",
    "port": 7090,
    "database": "VOYAGER"
  }
  // Add more server entries here...
]
```

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

4. Populate the `servers.json` file by running the **retrieve_loc_z3950_servers.py** and **test_loc_z3950_servers.py** scripts.

    ```bash
    python retrieve_loc_z3950_servers.py
    python test_loc_z3950_servers.py
    ```

    Ensure that the `servers.json` file is updated with working servers.

## Usage

To run the application:

```bash
python z3950search.py
```

The graphical user interface will open, allowing you to:

1. **Search by ISBN** or **Title/Author**.
2. **View results** and **navigate** through records.
3. **Download MARC records** to your local machine.

## Contributing

If you find any issues or have suggestions for improvement, feel free to open a pull request or file an issue on GitHub. Contributions are welcome!


