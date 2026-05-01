from workflows_cdk import Response, Request, ManagedError
from flask import request as flask_request
import requests
import os
from main import router

MONDAY_API_URL = "https://api.monday.com/v2"


@router.route("/execute", methods=["GET", "POST"])
def execute():
    """
    This is the function that is executed when you click on "Run" on a workflow that uses this action.
    """
    try:
        request = Request(flask_request)
        data = request.data

        # Validate required parameters
        if not data:
            raise ManagedError("Missing request parameters")

        if not data.get("api_key"):
            raise ManagedError("Missing API key parameter")

        if not data.get("container"):
            raise ManagedError("Missing container parameter")

        if not data.get("identifier"):
            raise ManagedError("Missing identifier parameter")

        api_token = data.get("api_key")
        container = data.get("container")
        identifier = data.get("identifier")

        # Build the headers
        headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
        }

        # Build the query based on the object type
        if container and identifier:
            query = f"""
            query ($identifier: [ID!], $limit: Int) {{
                {container}(ids: $identifier) {{
                    id
                    name
                    items_page(limit: $limit) {{
                    items {{
                        id
                        name
                    }}
                    }}
                }}
            }}
            """

        # Make the request
        response = requests.post(
            MONDAY_API_URL,
            json={
                "query": query,
                "variables": {"identifier": identifier, "limit": 50},
            },
            headers=headers,
        )

        return Response(data=response.json())
    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))


@router.route("/content", methods=["GET", "POST"])
def content():
    """
    This is the function that goes and fetches the necessary data to populate the possible choices in dynamic form fields.
    For example, if you have a module to delete a contact, you would need to fetch the list of contacts to populate the dropdown
    and give the user the choice of which contact to delete.

    An action's form may have multiple dynamic form fields, each with their own possible choices. Because of this, in the /content route,
    you will receive a list of content_object_names, which are the identifiers of the dynamic form fields. A /content route may be called for one or more content_object_names.

    Every data object takes the shape of:
    {
        "value": "value",
        "label": "label"
    }

    Args:
        data:
            form_data:
                form_field_name_1: value1
                form_field_name_2: value2
            content_object_names:
                [
                    {   "id": "containers"   }
                ]
        credentials:
            connection_data:
                value: (actual value of the connection)

    Return:
        {
            "content_objects": [
                {
                    "content_object_name": "containers",
                    "data": [{"value": "value1", "label": "label1"}]
                },
                ...
            ]
        }
    """
    try:
        request = Request(flask_request)

        data = request.data

        print(data)

        form_data = data.get("form_data", {})
        content_object_names = data.get("content_object_names", [])

        # Extract content object names from objects if needed
        if (
            isinstance(content_object_names, list)
            and content_object_names
            and isinstance(content_object_names[0], dict)
        ):
            content_object_names = [
                obj.get("id") for obj in content_object_names if "id" in obj
            ]

        content_objects = []  # this is the list of content objects that will be returned to the frontend

        api_token = form_data.get("api_key")
        container = form_data.get("container")

        if not api_token:
            raise ManagedError("Missing API key parameter")

        # Build the headers
        headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
        }

        query = """
            {
                boards(limit: 10) {
                    id
                    name
                    state
                    workspace_id
                }

                workspaces(limit: 10) {
                    id
                    name
                    kind
                }

                users(limit: 10) {
                    id
                    name
                    email
                }

                teams {
                    id
                    name
                }

                tags {
                    id
                    name
                }

                docs(limit: 10) {
                    id
                    name
                }

                folders(limit: 10) {
                    id
                    name
                }

                account {
                    id
                    name
                }
            }
        """
        response = requests.post(MONDAY_API_URL, json={"query": query}, headers=headers)
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            raise ManagedError(f"Monday.com API error: {result['errors']}")

        for content_object_name in content_object_names:
            if content_object_name == "containers":
                top_modules = result["data"].keys()
                data = [{"value": module, "label": module} for module in top_modules]

                content_objects.append(
                    {"content_object_name": "containers", "data": data}
                )

            elif content_object_name == "identifiers" and container:
                data = [
                    {"value": record["id"], "label": record["name"]}
                    for record in result["data"][container]
                ]

                content_objects.append(
                    {"content_object_name": "identifiers", "data": data}
                )

        return Response(data={"content_objects": content_objects})

    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))
