import requests
from workflows_cdk import ManagedError

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


def get_query_args(object_type: str, token: str) -> dict:
    """
    Returns a dict with:
      - "args": the list of GraphQL argument definitions for the query
      - "return_type": the raw introspection type of what the query returns

    Both are needed by /execute: args drive validation + variable building,
    and return_type determines whether to include a selection set (objects need
    "{ id name }", scalars like JSON have no subfields and need nothing.
    """
    query = """
        query {
            __type(name: "Query") {
                fields {
                    name
                    type {
                        name
                        kind
                        ofType {
                            name
                            kind
                        }
                    }
                    args {
                        name
                        description
                        type {
                            name
                            kind
                            ofType {
                                name
                                kind
                                ofType {
                                    name
                                    kind
                                    ofType {
                                        name
                                        kind
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    """
    result = run_monday_query(query=query, token=token)
    for field in result["data"]["__type"]["fields"]:
        if field["name"] == object_type:
            return {"args": field["args"], "return_type": field["type"]}
    return {"args": [], "return_type": {"kind": "SCALAR", "name": None}}
