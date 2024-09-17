"""
This script checks if a set of Z39.50 servers requires authentication by attempting to
connect using `yaz-client` and issuing simple queries. It saves servers that do
exist and do not require authentication to a JSON file.

Enhancements:
- Utilizes multithreading with `ThreadPoolExecutor` to run checks concurrently,
  significantly reducing the total execution time.
- Implements robust exception handling to gracefully handle various error scenarios.
"""

import subprocess
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError


def check_server_and_authentication(server_data, timeout=10):
    """
    Checks if a specified server requires authentication by attempting to
    connect using yaz-client and issuing a simple query.

    Args:
        server_data (dict): A dictionary containing the server information:
            - 'name' (str): Server name
            - 'host' (str): Hostname or IP of the server
            - 'port' (int): Port number to connect to
            - 'database' (str): Database name on the server
        timeout (int, optional): Timeout in seconds for server connection. Default is 10.

    Returns:
        tuple: A tuple containing:
            - success (bool): True if the server does not require authentication and
              the connection was successful, False otherwise.
            - server_data (dict): The server information passed in.

    The function handles various exceptions and returns False along with the server data
    if an error occurs or if authentication is required.

    Exceptions are caught and logged within the function to prevent them from propagating.
    """
    try:
        cmd = [
            "yaz-client",
            f'{server_data["host"]}:{server_data["port"]}/{server_data["database"]}',
        ]

        print(
            f"[INFO] Checking {server_data['name']} "
            f"({server_data['host']}:{server_data['port']}/{server_data['database']})..."
        )

        with subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as process:
            yaz_commands = "find water\nshow 1\n"
            stdout, stderr = process.communicate(yaz_commands, timeout=timeout)

            # Consolidate responses and return accordingly
            if "Could not resolve address" in stderr:
                response = (
                    f"[ERROR] Could not resolve address for {server_data['name']}."
                )
                success = False
            elif "authentication" in stderr.lower() or "auth" in stderr.lower():
                response = f"[INFO] {server_data['name']} requires authentication."
                success = False
            elif any(
                keyword in stdout.lower()
                for keyword in ["connection accepted", "record type", "number of hits"]
            ):
                response = (
                    f"[INFO] {server_data['name']} does not require authentication "
                    "and returned results."
                )
                success = True
            elif "records returned: 0" in stdout.lower():
                response = (
                    f"[INFO] {server_data['name']} does not require authentication "
                    "(but returned no results)."
                )
                success = True
            else:
                response = f"[WARNING] Unexpected response from {server_data['name']}: {stderr}"
                success = False

            print(response)
            return success, server_data
    except subprocess.TimeoutExpired:
        response = f"[ERROR] Connection to {server_data['name']} timed out after {timeout} seconds."
        print(response)
        return False, server_data
    except OSError as err:
        response = (
            f"[ERROR] An OS error occurred while checking {server_data['name']}: {err}"
        )
        print(response)
        return False, server_data
    except Exception as exc:
        response = (
            f"[ERROR] An unexpected error occurred while checking {server_data['name']}: "
            f"{exc}"
        )
        print(response)
        return False, server_data


def save_servers_to_file(servers, file_name):
    """
    Saves the list of server information to a JSON file.

    Args:
        servers (list): A list of dictionaries containing the server information.
        file_name (str): The name of the file to save the JSON data.

    Raises:
        OSError: If there is an error while writing to the file.
    """
    try:
        with open(file_name, "w", encoding="utf-8") as json_file:
            json.dump(servers, json_file, indent=4)
        print(
            f"[INFO] Successfully saved {len(servers)} non-authenticated servers to {file_name}."
        )
    except OSError as err:
        print(f"[ERROR] An error occurred while saving to {file_name}: {err}")


if __name__ == "__main__":
    # Main execution block:
    # - Loads the server information from a JSON file ('loc_servers.json').
    # - Checks servers concurrently using ThreadPoolExecutor.
    # - Saves servers that do not require authentication to 'non_auth_loc_servers.json'.

    try:
        with open("loc_servers.json", "r", encoding="utf-8") as loc_file:
            servers_list = json.load(loc_file)
            total_servers = len(servers_list)
            print(f"[INFO] Loaded {total_servers} servers from 'loc_servers.json'.")
    except FileNotFoundError:
        print(
            "[ERROR] No 'loc_servers.json' file found. Please ensure the file exists."
        )
        sys.exit(1)

    non_auth_servers = []

    MAX_WORKERS = 200  # Adjust this number based on your system's capabilities

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_server = {
            executor.submit(check_server_and_authentication, srv, timeout=10): srv
            for srv in servers_list
        }

        for future in as_completed(future_to_server):
            srv = future_to_server[future]
            try:
                successful, srv_data = future.result()
                if successful:
                    non_auth_servers.append(srv_data)
            except CancelledError:
                print(f"[ERROR] Task for {srv['name']} was cancelled.")
            except Exception as exc:
                print(f"[ERROR] An unexpected error occurred for {srv['name']}: {exc}")
                raise

    save_servers_to_file(non_auth_servers, "non_auth_loc_servers.json")

    print("[INFO] Finished checking servers.")
