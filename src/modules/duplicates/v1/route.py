import requests
from flask import request as flask_request
from main import router
from src.monday_client import get_mutation_args, run_monday_query
from .utility import (
    build_mutation_vars,
    build_schema_from_args,
    build_selection,
    humanize,
)
from workflows_cdk import ManagedError, Request, Response

MONDAY_API_URL = "https://api.monday.com/v2"


@router.route("/execute", methods=["GET", "POST"])
def execute():
    """
    This is the function that is executed when you click on "Run" on a workflow that uses this action.
    """
    try:
        request = Request(flask_request)
        data = request.data

        if not data:
            raise ManagedError("Missing request parameters")
        if not data.get("api_key"):
            raise ManagedError("Missing API key parameter")
        if not data.get("object_type"):
            raise ManagedError("Missing object type parameter")

        api_token = data.get("api_key")
        object_type = data.get("object_type")

        headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
        }

        # Records are keyed by object_type in the payload
        records = data.get(object_type)
        if not records:
            raise ManagedError("Missing records parameter")

        # Fetch args + return type for this mutation via introspection.
        # args drive validation and variable building; return_type determines
        # whether the mutation returns an object (needs "{ id name }") or a
        # scalar like JSON (no subfields — selection set must be omitted).
        mutation_info = get_mutation_args(object_type, api_token)
        args = mutation_info["args"]
        if not args:
            raise ManagedError(f"Unsupported object type: {object_type}")

        return_type = mutation_info["return_type"]
        selection = build_selection(return_type, api_token)

        # Validate and build mutation vars in a single pass.
        # build_mutation_vars resolves each arg's type, extracts the value from the record,
        # and returns the GQL variable declarations, argument strings, and variable values
        # needed to construct the mutation. If any required field is missing it raises
        # immediately — nothing is sent to Monday.com until all records are clean.
        var_decls = []
        alias_blocks = []
        variables = {}

        for i, record in enumerate(records):
            rec_var_decls, arg_strings, rec_variables, missing = build_mutation_vars(
                args, record, i
            )
            if missing:
                raise ManagedError(f"{missing[0]} is required")
            var_decls.extend(rec_var_decls)
            variables.update(rec_variables)
            # Each record gets an alias (record_0, record_1, …) so all records
            # are created in a single HTTP round-trip and results can be mapped back by index.
            alias_blocks.append(
                f"record_{i}: {object_type}({', '.join(arg_strings)}) {selection}".strip()
            )

        mutation = f"mutation ({', '.join(var_decls)}) {{ {' '.join(alias_blocks)} }}"

        response = requests.post(
            MONDAY_API_URL,
            json={"query": mutation, "variables": variables},
            headers=headers,
        )
        response.raise_for_status()
        api_result = response.json()

        if "errors" in api_result:
            raise ManagedError(str(api_result["errors"]))

        # Map each aliased result back to its original record by index.
        # Scalar-returning mutations (e.g. duplicate_board → JSON) give a raw value,``
        # not a dict, so we only spread the result when it's an object.
        results = []
        for i in range(len(records)):
            result_data = api_result["data"].get(f"record_{i}")
            if result_data is None:
                raise ManagedError(f"No data returned for record {i + 1}")
            entry = {"success": True}
            if isinstance(result_data, dict):
                entry.update(result_data)
            results.append(entry)

        return Response(
            data={"results": results},
            metadata={"affected_rows": len(results)},
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

        # Fetch all Mutation field names via introspection so we can derive the
        # available object types without hardcoding them.
        result = run_monday_query(
            query='{ __type(name: "Mutation") { fields { name } } }',
            token=api_token,
        )

        content_objects = []

        for content_object_name in content_object_names:
            if content_object_name == "object_types":
                # Filter to duplicate_* mutations and convert to value/label pairs.
                mutations = result["data"]["__type"]["fields"]
                object_types = [
                    {
                        "value": mutation["name"],
                        "label": humanize(mutation["name"].removeprefix("duplicate_")),
                    }
                    for mutation in mutations
                    if mutation["name"].startswith("duplicate_")
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

        # Use GraphQL introspection to discover the args for the selected mutation.
        # build_schema_from_args converts each arg into a form field definition,
        # fetching enum values from the API where needed.
        args = get_mutation_args(object_type, api_key)["args"]
        fields, ui_order = build_schema_from_args(args, api_key)

        # Wrap the generated fields in an array field so the user can change
        # multiple columns in one workflow execution.
        return Response(
            data={
                "schema": {
                    "metadata": BASE_METADATA,
                    "fields": [
                        *BASE_FIELDS,
                        {
                            "id": object_type,
                            "type": "array",
                            "label": f"{humanize(object_type)}",
                            "description": f"List of {humanize(object_type)}",
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
