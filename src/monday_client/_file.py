import json

import requests

MONDAY_FILE_URL = "https://api.monday.com/v2/file"

def run_monday_file_upload(
    query: str,
    variables: dict,
    file_bytes: bytes,
    filename: str,
    token: str,
) -> dict:
    """
    Sends a file-upload mutation to Monday.com's multipart /v2/file endpoint.

    query must declare $file: File! and reference it in the mutation args.
    Non-file variables are passed as a JSON 'variables' form field; the file
    binary is passed as 'variables[file]'.

    Returns the raw API response dict. Raises requests.HTTPError on transport
    errors; callers are responsible for checking 'errors' in the result.
    """
    response = requests.post(
        MONDAY_FILE_URL,
        headers={"Authorization": token},
        files={
            "query": (None, query),
            "variables": (None, json.dumps(variables)),
            "variables[file]": (filename, file_bytes),
        },
    )
    response.raise_for_status()
    return response.json()
