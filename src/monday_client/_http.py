import time

import requests
from workflows_cdk import ManagedError

MONDAY_API_URL = "https://api.monday.com/v2"

_MAX_RETRIES = 3

# TEMP TEST FLAG — set to True to simulate a 429 on the first attempt.
# Remove this block (and the 3 lines that reference it in run_monday_query) when done testing.
_SIMULATE_429 = False
_simulate_429_fired = False


def _retry_seconds(response: requests.Response, result: dict | None) -> int | None:
    """
    Returns how many seconds to wait before retrying, or None if not retryable.

    Monday.com signals rate limiting in two ways:
    - HTTP 429 (IP-based limit): honour Retry-After header, default 10s
    - GraphQL error with retry_in_seconds in extensions (complexity budget exhausted)
    Both are transient — safe to retry after the indicated delay.
    5xx responses are server-side transients; retry with exponential backoff.
    """
    if response.status_code == 429:
        return int(response.headers.get("Retry-After", 10))
    if response.status_code >= 500:
        return None  # caller uses 2^attempt backoff
    if result:
        for error in result.get("errors") or []:
            wait = (error.get("extensions") or {}).get("retry_in_seconds")
            if wait is not None:
                return int(wait)
    return None


def run_monday_query(query: str, token: str, variables: dict = None):
    """
    Executes a GraphQL query or mutation against the Monday.com API.

    Retries up to _MAX_RETRIES times on:
    - HTTP 429 (IP rate limit) — waits Retry-After seconds
    - HTTP 5xx (server error) — waits 2^attempt seconds
    - GraphQL complexity budget errors (retry_in_seconds in error extensions)

    Raises ManagedError on API-level errors and after all retries are exhausted.
    """
    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    for attempt in range(_MAX_RETRIES + 1):
        # TEMP: simulate a 429 on the very first attempt to test retry logic.
        global _simulate_429_fired
        if _SIMULATE_429 and not _simulate_429_fired:
            _simulate_429_fired = True
            print(f"[TEST] Simulating 429 on attempt {attempt} for query {query}, will retry in 10s")
            time.sleep(10)
            continue

        response = requests.post(MONDAY_API_URL, headers=headers, json=payload)

        result = None
        if response.ok:
            result = response.json()

        wait = _retry_seconds(response, result)

        if response.status_code == 429 or response.status_code >= 500:
            if attempt == _MAX_RETRIES:
                raise ManagedError(
                    f"Monday.com request failed after {_MAX_RETRIES} retries "
                    f"(status {response.status_code})"
                )
            time.sleep(wait if wait is not None else 2 ** attempt)
            continue

        response.raise_for_status()

        if result and "errors" in result:
            if wait is not None and attempt < _MAX_RETRIES:
                time.sleep(wait)
                continue
            raise ManagedError(f"Monday.com API error: {result['errors']}")

        return result
