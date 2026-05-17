import time

import requests
from graphql import parse as gql_parse
from graphql.error import GraphQLSyntaxError
from workflows_cdk import ManagedError

MONDAY_API_URL = "https://api.monday.com/v2"

# Seconds to wait before retry 1 and retry 2.
_RETRY_DELAY_SECONDS = (3, 5)


def run_monday_query(query: str, token: str, variables: dict = None):
    """
    Executes a GraphQL query or mutation against the Monday.com API.

    Validates query syntax locally before sending. Retries twice on transient
    failures (HTTP 429 / 5xx) — waiting 3 s then 5 s between attempts.
    For 429 responses, honours the Retry-After header if it exceeds the default delay.
    Raises ManagedError on persistent failure or API-level errors.
    """
    try:
        gql_parse(query)
    except GraphQLSyntaxError as e:
        raise ManagedError(f"Invalid GraphQL syntax: {e.message}")

    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    for attempt in range(len(_RETRY_DELAY_SECONDS) + 1):
        response = requests.post(
            MONDAY_API_URL, headers=headers, json=payload, timeout=30
        )

        if response.status_code == 429 or response.status_code >= 500:
            if attempt == len(_RETRY_DELAY_SECONDS):
                raise ManagedError(
                    f"Monday.com is temporarily unavailable "
                    f"(status {response.status_code}). Please try again in a few minutes."
                )
            if response.status_code == 429:
                # Respect the server's requested wait time if longer than our default.
                delay = max(
                    int(response.headers.get("Retry-After", 0)),
                    _RETRY_DELAY_SECONDS[attempt],
                )
            else:
                delay = _RETRY_DELAY_SECONDS[attempt]
            time.sleep(delay)
            continue

        response.raise_for_status()

        result = response.json()
        if "errors" in result:
            raise ManagedError(f"Monday.com API error: {result['errors']}")

        return result
