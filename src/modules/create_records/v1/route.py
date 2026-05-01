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

        if not data.get("object_type"):
            raise ManagedError("Missing object type parameter")
        
        if not data.get("records"):
            raise ManagedError("Missing information to create the records")

#     'records': [{'board_name': 'test name', 'kind': 'public'}]

        api_token = data.get("api_key")
        object_type = data.get("object_type")
        records = data.get("records")

        headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
        }

        results = []

        if object_type == "boards":
            mutation = """
                mutation ($board_name: String!, $board_kind: BoardKind!) {
                    create_board(board_name: $board_name, board_kind: $board_kind) {
                        id
                        name
                        state
                    }
                }
            """
            for record in records:
                board_name = record.get("board_name")
                kind = record.get("kind", "public")

                if not board_name:
                    results.append({
                        "success": False,
                        "error": "board_name is required",
                        "record": record,
                    })
                    continue

                response = requests.post(
                    MONDAY_API_URL,
                    json={
                        "query": mutation,
                        "variables": {"board_name": board_name, "board_kind": kind},
                    },
                    headers=headers,
                )
                response.raise_for_status()
                result = response.json()

                if "errors" in result:
                    results.append({
                        "success": False,
                        "error": result["errors"],
                        "record": record,
                    })
                else:
                    created = result["data"]["create_board"]
                    results.append({
                        "success": True,
                        "id": created["id"],
                        "name": created["name"],
                        "state": created["state"],
                    })
        else:
            raise ManagedError(f"Unsupported object type: {object_type}")

        successful = sum(1 for r in results if r["success"])
        return Response(
            data={"results": results},
            metadata={"affected_rows": successful},
        )
    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))


@router.route("/content", methods=["GET", "POST"])
def content():
    try:
        request = Request(flask_request)

        data = request.data

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
        # object_type = form_data.get("object_type")

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
            if content_object_name == "object_types":
                top_modules = result["data"].keys()
                data = [{"value": module, "label": module} for module in top_modules]

                content_objects.append(
                    {"content_object_name": "object_types", "data": data}
                )

        return Response(data={"content_objects": content_objects})

    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))


BASE_METADATA = {"workflows_module_schema_version": "1.0.0"}
BASE_FIELDS = [
    {
        "id": "api_key",
        "type": "string",
        "label": "API Key",
        "description": "Your API key for authentication with Monday.com",
        "validation": {"required": True},
    },
    {
        "id": "object_type",
        "type": "string",
        "label": "Object Type",
        "description": "Select the object type to reveal its specific fields",
        "validation": {"required": True},
        "on_action": {"load_schema": True},
        "choices": {"values": []},
        "content": {
            "type": ["managed"],
            "content_objects": [{"id": "object_types"}],
        },
        "ui_options": {"ui_widget": "SelectWidget"},
    },
]
BASE_UI_OPTIONS = {"ui_order": ["api_key", "object_type"]}


@router.route("/schema", methods=["GET", "POST"])
def schema():
    try:
        request = Request(flask_request)
        data = request.data

        form_data = data.get("form_data", {})
        object_type = form_data.get("object_type")
        api_key = form_data.get("api_key")
        
        print(form_data)

        response = Response(
            data={
                "schema": {
                    "metadata": BASE_METADATA,
                    "fields": BASE_FIELDS,
                    "ui_options": BASE_UI_OPTIONS,
                }
            }
        )

        if not api_key:
            return response

        if object_type == "boards":
            boards_fields = [
                {
                    "default": [{}],
                    "description": "List of boards to create",
                    "id": "records",
                    "items": {
                        "default": {},
                        "fields": [
                            {
                                "default": "",
                                "description": "The name of the board",
                                "id": "board_name",
                                "label": "Board Name",
                                "type": "string",
                                "validation": {"required": True},
                            },
                            {
                                "default": "",
                                "description": "The kind of board",
                                "id": "kind",
                                "label": "Kind",
                                "type": "string",
                                "validation": {"required": True},
                            },
                        ],
                        "type": "object",
                        "ui_options": {
                            "ui_order": [
                                "board_name",
                                "kind",
                            ]
                        },
                    },
                    "label": "Records",
                    "type": "array",
                    "validation": {"min_items": 1},
                },
            ]
            return Response(
                data={
                    "schema": {
                        "metadata": BASE_METADATA,
                        "fields": [
                            *BASE_FIELDS,
                            *boards_fields,
                        ],
                        "ui_options": {
                            "ui_order": ["api_key", "object_type", "records"]
                        },
                    }
                }
            )

        return response
    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))
