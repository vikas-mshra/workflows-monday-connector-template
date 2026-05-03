import requests
from workflows_cdk import ManagedError

MONDAY_API_URL = "https://api.monday.com/v2"


def run_monday_query(query: str, token: str, variables: dict = None):
    """∏
    Executes a GraphQL query or mutation against the Monday.com API.

    Raises ManagedError on API-level errors (GraphQL errors in the response body)
    and raises requests.HTTPError on transport-level failures (4xx/5xx).
    """
    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    response = requests.post(MONDAY_API_URL, headers=headers, json=payload)
    response.raise_for_status()

    result = response.json()
    if "errors" in result:
        raise ManagedError(f"Monday.com API error: {result['errors']}")

    return result
