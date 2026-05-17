from pathlib import Path

from flask import request as flask_request
from workflows_cdk import ManagedError, Request, Response

from main import router
from src.monday_client import get_query_args, run_monday_query
from src.monday_content import build_content_response
from src.monday_schema import humanize, resolve_record_to_gql_args
from src.utils.schema_loader import build_schema_response


@router.route("/execute", methods=["GET", "POST"])
def execute():
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

        # Records are keyed by object_type in the payload (e.g. "boards": [...])
        records = data.get(object_type)
        if not records:
            raise ManagedError("Missing records parameter")

        # Fetch args + return type for this query via introspection.
        query_info = get_query_args(object_type, api_key)
        args = query_info["args"]
        if not args:
            raise ManagedError(f"Unsupported object type: {object_type}")

        # Unwrap the return type to find the element type name (e.g. Board from [Board]).
        # Then introspect that type's fields and select only scalar/enum ones.
        # This avoids hardcoding { id name } and returns all flat fields instead.
        return_type = query_info["return_type"]
        unwrapped_return_type = return_type
        if unwrapped_return_type.get("kind") == "NON_NULL":
            unwrapped_return_type = (
                unwrapped_return_type.get("ofType") or unwrapped_return_type
            )
        if unwrapped_return_type.get("kind") == "LIST":
            unwrapped_return_type = (
                unwrapped_return_type.get("ofType") or unwrapped_return_type
            )
            if unwrapped_return_type.get("kind") == "NON_NULL":
                unwrapped_return_type = (
                    unwrapped_return_type.get("ofType") or unwrapped_return_type
                )

        element_type = (
            unwrapped_return_type.get("name")
            if unwrapped_return_type.get("kind") == "OBJECT"
            else None
        )

        if element_type:
            type_result = run_monday_query(
                query=f'{{ __type(name: "{element_type}") {{ fields {{ name type {{ kind ofType {{ kind }} }} }} }} }}',
                token=api_key,
            )
            type_fields = (
                (type_result["data"].get("__type") or {}).get("fields")
            ) or []
            scalar_names = [
                f["name"]
                for f in type_fields
                if (f["type"].get("ofType") or f["type"]).get("kind")
                in ("SCALAR", "ENUM")
            ]
            selection = (
                ("{ " + " ".join(scalar_names) + " }")
                if scalar_names
                else "{ id name }"
            )
        else:
            selection = (
                ""
                if unwrapped_return_type.get("kind") in ("SCALAR", "ENUM")
                else "{ id name }"
            )

        # Build query vars per record. build_query_vars also collects any
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
            # Each record gets an alias so all queries run in a single HTTP round-trip.
            alias_blocks.append(
                f"record_{record_index}: {object_type}({', '.join(arg_strings)}) {selection}".strip()
            )

        var_clause = f"({', '.join(var_decls)})" if var_decls else ""
        gql_query = f"query {var_clause} {{ {' '.join(alias_blocks)} }}"

        api_result = run_monday_query(
            query=gql_query, token=api_key, variables=variables
        )

        results = []
        for record_index in range(len(records)):
            result_data = api_result["data"].get(f"record_{record_index}")
            if result_data is None:
                raise ManagedError(f"No data returned for record {record_index + 1}")
            result_entry = {"success": True}
            if isinstance(result_data, dict):
                result_entry.update(result_data)
            elif isinstance(result_data, list):
                result_entry["data"] = result_data
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
            {"value": f["name"], "label": humanize(f["name"])} for f in fields
        ],
        gql_root_type="Query",
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Query",
        lambda ot: f"{humanize(ot)} Records",
        lambda ot: f"List of {humanize(ot)} to retrieve",
    )
