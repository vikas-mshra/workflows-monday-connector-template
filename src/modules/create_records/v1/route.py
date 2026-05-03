from workflows_cdk import Response, Request, ManagedError
from flask import request as flask_request
import requests
from main import router

from model import get_mutation_args
from utility import build_schema_from_args, build_mutation_vars, humanize

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

        # Records are keyed by object_type in the payload (e.g. "create_board": [...])
        records = data.get(object_type)
        if not records:
            raise ManagedError("Missing records parameter")

        # Fetch the GraphQL argument definitions for this mutation via introspection.
        # This drives both validation and dynamic mutation building below.
        args = get_mutation_args(object_type, api_token)
        if not args:
            raise ManagedError(f"Unsupported object type: {object_type}")

        # Pre-validate each record against the required args.
        # Invalid records are added to results immediately; valid ones are batched.
        results = []
        valid = []
        for record in records:
            _, _, _, missing = build_mutation_vars(args, record, 0)
            if missing:
                results.append(
                    {
                        "success": False,
                        "error": f"{missing[0]} is required",
                        "record": record,
                    }
                )
            else:
                valid.append(record)

        if valid:
            var_decls = []
            alias_blocks = []
            variables = {}

            # Build a single batched mutation using aliases (record_0, record_1, …)
            # so all valid records are created in one HTTP round-trip.
            for i, record in enumerate(valid):
                rec_var_decls, arg_strings, rec_variables, _ = build_mutation_vars(
                    args, record, i
                )
                var_decls.extend(rec_var_decls)
                variables.update(rec_variables)
                alias_blocks.append(
                    f"record_{i}: {object_type}({', '.join(arg_strings)}) {{ id name }}"
                )

            mutation = (
                f"mutation ({', '.join(var_decls)}) {{ {' '.join(alias_blocks)} }}"
            )

            response = requests.post(
                MONDAY_API_URL,
                json={"query": mutation, "variables": variables},
                headers=headers,
            )
            response.raise_for_status()
            api_result = response.json()

            if "errors" in api_result:
                # Top-level errors mean the entire batch failed
                for record in valid:
                    results.append(
                        {
                            "success": False,
                            "error": api_result["errors"],
                            "record": record,
                        }
                    )
            else:
                # Map each aliased result back to its original record by index
                for i, record in enumerate(valid):
                    created = api_result["data"].get(f"record_{i}")
                    if created:
                        results.append({"success": True, **created})
                    else:
                        results.append(
                            {
                                "success": False,
                                "error": "No data returned",
                                "record": record,
                            }
                        )

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

        if not api_token:
            raise ManagedError("Missing API key parameter")

        # Build the headers
        headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
        }

        query = """
            {
                __type(name: "Mutation") {
                    fields {
                        name
                    }
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
                mutations = result["data"]["__type"]["fields"]
                object_types = [
                    {
                        "value": mutation["name"],
                        "label": humanize(mutation["name"].removeprefix("create_")),
                    }
                    for mutation in mutations
                    if mutation["name"].startswith("create_")
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
        args = get_mutation_args(object_type, api_key)
        fields, ui_order = build_schema_from_args(args, api_key)

        # Wrap the generated fields in an array field so the user can create
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
                            "description": f"List of {humanize(object_type)} to create",
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
