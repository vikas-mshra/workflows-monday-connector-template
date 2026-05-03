import json
import time

import requests
from workflows_cdk import ManagedError

MONDAY_FILE_URL = "https://api.monday.com/v2/file"

_MAX_RETRIES = 3


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

    Retries up to _MAX_RETRIES times on HTTP 429 and 5xx responses.
    Raises ManagedError after all retries are exhausted or on non-retryable errors.
    """
    for attempt in range(_MAX_RETRIES + 1):
        response = requests.post(
            MONDAY_FILE_URL,
            headers={"Authorization": token},
            files={
                "query": (None, query),
                "variables": (None, json.dumps(variables)),
                "variables[file]": (filename, file_bytes),
            },
        )

        if response.status_code == 429 or response.status_code >= 500:
            if attempt == _MAX_RETRIES:
                raise ManagedError(
                    f"Monday.com file upload failed after {_MAX_RETRIES} retries "
                    f"(status {response.status_code})"
                )
            wait = int(response.headers.get("Retry-After", 2 ** attempt))
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response.json()
