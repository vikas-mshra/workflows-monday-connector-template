import requests
from workflows_cdk import Response, Request, ManagedError

MONDAY_API_URL = "https://api.monday.com/v2"

def run_monday_query(query: str, token: str, variables: dict = None):

    headers = {"Authorization": token, "Content-Type": "application/json"}

    payload = {"query": query}

    # optional GraphQL variables support
    if variables:
        payload["variables"] = variables

    response = requests.post(MONDAY_API_URL, headers=headers, json=payload)

    # raise error if request failed
    response.raise_for_status()

    result = response.json()

    if "errors" in result:
        raise ManagedError(f"Monday.com API error: {result['errors']}")

    return result
