from workflows_cdk import Response, Request, ManagedError
from flask import request as flask_request
import requests
from main import router
from model1 import get_query_args, run_monday_query
from utility import build_schema_from_args, humanize

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

        if not data.get("identifier"):
            raise ManagedError("Missing identifier parameter")

        api_key = data.get("api_key")
        object_type = data.get("object_type")
        identifier = data.get("identifier")

        # Build the headers
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }

        # Build the query based on the object type
        if object_type and identifier:
            query = f"""
            query ($identifier: [ID!], $limit: Int) {{
                {object_type}(ids: $identifier) {{
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
    try:
        request = Request(flask_request)

        data = request.data

        form_data = data.get("form_data", {})
        content_object_names = data.get("content_object_names", [])

        # content_object_names may arrive as a list of id-objects; flatten to plain strings
        if (
            isinstance(content_object_names, list)
            and content_object_names
            and isinstance(content_object_names[0], dict)
        ):
            content_object_names = [
                obj.get("id") for obj in content_object_names if "id" in obj
            ]

        api_token = form_data.get("api_key")

        if not api_token:
            raise ManagedError("Missing API key parameter")

        # Fetch all Query field names via introspection so we can derive the
        # available object types without hardcoding them.
        result = run_monday_query(
            query='{ __type(name: "Query") { fields { name } } }',
            token=api_token,
        )

        content_objects = []

        for content_object_name in content_object_names:
            if content_object_name == "object_types":
                queries = result["data"]["__type"]["fields"]
                object_types = [
                    {"value": query["name"], "label": humanize(query["name"])}
                    for query in queries
                ]
                content_objects.append(
                    {"content_object_name": "object_types", "data": object_types}
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
        "description": "Select the object type to get records for",
        "validation": {"required": True},
        "on_action": {"load_schema": True},
        "choices": {"values": []},
        "content": {"type": ["managed"], "content_objects": [{"id": "object_types"}]},
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
        api_key = form_data.get("api_key")
        object_type = form_data.get("object_type")

        # Base schema: just the api_key + object_type selector fields.
        # Returned immediately if the user hasn't filled in the api_key or
        # hasn't selected an object_type yet.
        response = Response(
            data={
                "schema": {
                    "metadata": BASE_METADATA,
                    "fields": BASE_FIELDS,
                    "ui_options": BASE_UI_OPTIONS,
                }
            }
        )

        if not api_key or not object_type:
            return response

        # Use GraphQL introspection to discover the args for the selected query.
        # build_schema_from_args converts each arg into a form field definition,
        # fetching enum values from the API where needed.
        args = get_query_args(object_type, api_key)["args"]
        if not args:
            return response

        fields, ui_order = build_schema_from_args(args, api_key)

        # Wrap the generated fields in an array field so the user can get
        # multiple records in one workflow execution.
        return Response(
            data={
                "schema": {
                    "metadata": BASE_METADATA,
                    "fields": [
                        *BASE_FIELDS,
                        {
                            "id": object_type,
                            "type": "array",
                            "label": f"{humanize(object_type)} Records",
                            "description": f"List of {humanize(object_type)} to retrieve",
                            "default": [{}],
                            "items": {
                                "type": "object",
                                "default": {},
                                "fields": fields,
                                "ui_options": {"ui_order": ui_order},
                            },
                        },
                    ],
                    "ui_options": {"ui_order": ["api_key", "object_type", object_type]},
                }
            }
        )
    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))
