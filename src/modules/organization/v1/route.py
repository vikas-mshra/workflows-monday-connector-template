import requests
from flask import request as flask_request
from main import router
from src.monday_client import get_mutation_args
from src.monday_config import (
    BASE_FIELDS,
    BASE_METADATA,
    BASE_UI_OPTIONS,
    MONDAY_API_URL,
)
from src.monday_content import build_content_response
from src.monday_schema import build_mutation_vars, build_schema_from_args, humanize
from workflows_cdk import ManagedError, Request, Response


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

        # Records are keyed by object_type in the payload (e.g. "change_column": [...])
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

        # Strip NON_NULL wrapper to get the base return kind.
        return_type = mutation_info["return_type"]
        base_return_kind = (return_type.get("ofType") or return_type).get("kind")
        selection = "" if base_return_kind in ("SCALAR", "ENUM") else "{ id name }"

        # Build mutation vars per record. build_mutation_vars also collects any
        # missing required fields in the same pass — we raise a clear ManagedError
        # instead of letting the request reach Monday.com.
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

        if not var_decls:
            raise ManagedError(f"No arguments provided for {object_type}")
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
        # Scalar-returning mutations (e.g. update_board → JSON) give a raw value,
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
    return build_content_response(
        flask_request,
        lambda fields: [
            {"value": f["name"], "label": humanize(f["name"])}
            for f in fields
            if (
                f["name"].startswith("move_")
                or f["name"].startswith("connect_project_")
                or f["name"].startswith("enroll_items_")
                or f["name"].startswith("change_item")
            )
        ],
    )


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
