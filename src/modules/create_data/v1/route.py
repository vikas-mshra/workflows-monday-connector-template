from pathlib import Path

from flask import request as flask_request
from workflows_cdk import ManagedError, Request, Response

from main import router
from src.monday_client import get_mutation_args, run_monday_query
from src.monday_content import build_content_response
from src.monday_schema import humanize, resolve_record_to_gql_args
from src.utils.schema_loader import build_schema_response


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

        api_key = data.get("api_key")
        object_type = data.get("object_type")

        # Records are keyed by object_type in the payload (e.g. "create_board": [...])
        records = data.get(object_type)
        if not records:
            raise ManagedError("Missing records parameter")

        # Fetch args + return type for this mutation via introspection.
        # args drive validation and variable building; return_type determines
        # whether the mutation returns an object (needs "{ id name }") or a
        # scalar like JSON (no subfields — selection set must be omitted).
        mutation_info = get_mutation_args(object_type, api_key)
        args = mutation_info["args"]
        if not args:
            raise ManagedError(f"Unsupported object type: {object_type}")

        # Strip NON_NULL wrapper to get the base return kind.
        return_type = mutation_info["return_type"]
        base_return_kind = (return_type.get("ofType") or return_type).get("kind")
        selection = "" if base_return_kind in ("SCALAR", "ENUM") else "{ id }"

        # Build mutation vars per record. build_mutation_vars also collects any
        # missing required fields in the same pass — we raise a clear ManagedError
        # instead of letting the request reach Monday.com.
        var_decls = []
        alias_blocks = []
        variables = {}

        for record_index, record in enumerate(records):
            record_var_decls, arg_strings, record_variables, missing = (
                resolve_record_to_gql_args(args, record, record_index)
            )
            if missing:
                raise ManagedError(f"{missing[0]} is required")
            var_decls.extend(record_var_decls)
            variables.update(record_variables)
            # Each record gets an alias (record_0, record_1, …) so all records
            # are created in a single HTTP round-trip and results can be mapped back by index.
            alias_blocks.append(
                f"record_{record_index}: {object_type}({', '.join(arg_strings)}) {selection}".strip()
            )

        var_clause = f"({', '.join(var_decls)})" if var_decls else ""
        mutation = f"mutation {var_clause} {{ {' '.join(alias_blocks)} }}"

        api_result = run_monday_query(
            query=mutation, token=api_key, variables=variables
        )

        # Map each aliased result back to its original record by index.
        # Scalar-returning mutations (e.g. update_board → JSON) give a raw value,
        # not a dict, so we only spread the result when it's an object.
        results = []
        for record_index in range(len(records)):
            result_data = api_result["data"].get(f"record_{record_index}")
            if result_data is None:
                raise ManagedError(f"No data returned for record {record_index + 1}")
            result_entry = {"success": True}
            if isinstance(result_data, dict):
                result_entry.update(result_data)
            results.append(result_entry)

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
            {
                "value": f["name"],
                "label": humanize(
                    f["name"].removeprefix("create_").removeprefix("or_get_")
                ),
            }
            for f in fields
            if f["name"].startswith("create_")
        ],
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Mutation",
        lambda ot: f"{humanize(ot)} Records",
        lambda ot: f"List of {humanize(ot)} to create",
    )
