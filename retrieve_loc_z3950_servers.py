"""
This script scrapes server information from the Library of Congress Z39.50 gateway page
and saves the extracted details into a JSON file with proper formatting and indentation.

Modules:
- json: For saving the scraped data in JSON format.
- requests: To make HTTP requests to retrieve the webpage content.
- bs4 (BeautifulSoup): To parse and navigate the HTML content of the pages.

Functions:
1. `get_server_links(main_url)`:
    - Fetches the main webpage and extracts links that contain "ACTION=INIT" to identify
      server information (name, host, and port).
    - Args:
        - `main_url` (str): URL of the main webpage to scrape.
    - Returns:
        - A list of dictionaries containing server details (name, url, host, port), or
          an empty list on failure.

2. `extract_server_info(server)`:
    - Scrapes individual server's webpage to extract the database information.
    - Args:
        - `server` (dict): Dictionary containing server details (name, url, host, port).
    - Returns:
        - A dictionary containing server information (name, host, port, database)
          or None in case of errors.

3. `save_all_server_info(servers_info, output_file)`:
    - Saves the collected server information into a properly formatted JSON file.
    - Args:
        - `servers_info` (list): A list of dictionaries containing server details.
        - `output_file` (str): Path to the output JSON file.

4. `main()`:
    - The main function orchestrates the scraping process, extracts server information
      from each link, and writes all data into a single JSON file with proper indentation.
    - It collects all server information in a list and writes the entire list to the output
      JSON file at the end.

Usage:
- When the script is executed, it fetches server data from the specified Library of Congress
  webpage, processes each server's information, and saves the results in a JSON file named
  "loc_servers.json" with an indentation of 4 spaces.

Error Handling:
- Each function includes exception handling to manage and report any potential errors
  during HTTP requests, data extraction, or file writing processes.
"""


import json
import requests
from bs4 import BeautifulSoup


def get_server_links(main_url):
    """
    Fetches the main webpage and extracts links containing "ACTION=INIT".

    Args:
      main_url (str): The URL of the main webpage to scrape.

    Returns:
      list: A list of dictionaries containing server information,
           including name, url, host, and port. Empty list on error.
    """
    try:
        response = requests.get(main_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Find all server links with host and port
        server_links = []
        for link in soup.find_all("a", href=True):
            if "ACTION=INIT" in link["href"]:
                # Extract host and port from the URL
                url_part = link["href"].split("FORM_HOST_PORT=")[-1]
                _, host, port = url_part.split(",")
                server_links.append(
                    {
                        "name": link.text.strip(),
                        "url": f"https://www.loc.gov{link['href']}",
                        "host": host,
                        "port": port,
                    }
                )
        return server_links

    except (requests.RequestException, ValueError) as e:
        print(f"Error retrieving main page: {str(e)}")
        return []


def extract_server_info(server):
    """
    Extracts database information from a server's webpage.

    Args:
      server (dict): A dictionary containing server information
                     (name, url, host, port).

    Returns:
      dict: A dictionary containing server information (name, host, port, database),
            or None on error.
    """
    try:
        response = requests.get(server["url"], timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        dbname = (
            soup.find("input", {"name": "dbname"})["value"]
            if soup.find("input", {"name": "dbname"})
            else "Default"
        )

        server_info = {
            "name": server["name"],
            "host": server["host"],
            "port": server["port"],
            "database": dbname,
        }
        return server_info

    except (requests.RequestException, ValueError) as e:
        print(f"Error extracting data from {server['url']}: {str(e)}")
        return None


def save_all_server_info(servers_info, output_file):
    """
    Saves all server information as a properly formatted JSON array to a file.

    Args:
      servers_info (list): A list of dictionaries containing server information.
      output_file (str): The path to the output file.
    """
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(servers_info, f, indent=4)


def main():
    """
    The main function that orchestrates the process of scraping and saving server information.
    """
    base_url = "https://www.loc.gov/z3950/gateway.html"
    output_file = "loc_servers.json"
    all_servers_info = []

    server_links = get_server_links(base_url)
    if not server_links:
        print("No server links found.")
        return

    for index, server in enumerate(server_links):
        print(
            f"Processing {index+1}/{len(server_links)}: {server['name']} at {server['url']}..."
        )
        server_info = extract_server_info(server)
        if server_info:
            all_servers_info.append(server_info)  # Collect all server information

    save_all_server_info(all_servers_info, output_file)

    print(f"Finished processing. Servers information saved to {output_file}.")


if __name__ == "__main__":
    main()
