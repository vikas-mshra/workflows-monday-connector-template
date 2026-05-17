from typing import Callable, Optional

from workflows_cdk import ManagedError, Request, Response

from src.monday_client import run_monday_query
from src.monday_schema import build_request_variables


def execute_batched_operation(
    flask_request,
    *,
    resolve_operation: Callable[[str, str], tuple],
    operation_keyword: str = "mutation",
    list_result_key: Optional[str] = None,
) -> Response:
    """
    Shared /execute handler for every Monday.com module.

    All modules' /execute endpoints share the same shape: parse the request,
    look up the operation's args + selection set, build a single batched
    GraphQL operation that runs all records via aliases in one HTTP round-trip,
    then map results back to each record by index. The only per-module
    differences are how args/selection are computed (introspection vs cached
    type_map; legacy `{ id }` vs build_response_selection), whether the
    operation is a mutation or a query, and how list-shaped results are keyed.
    This function captures everything else.

    Parameters:
      flask_request: incoming Flask request — same object passed to
          @router.route("/execute") handlers.
      resolve_operation: callable (object_type, api_key) -> (args, selection).
          Module-specific lookup that fetches the GraphQL arg definitions and
          builds the response selection set string. Kept as a callable so each
          module can choose its introspection strategy (legacy per-call API
          lookup vs cached type_map) without duplicating the rest of the flow.
      operation_keyword: "mutation" (default) or "query".
      list_result_key: when a record's result is a list, store it under this
          key inside the result entry. get_data uses "data", add_data uses
          "items". None drops list-shaped results — modules that never return
          lists don't need to set this.
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

        api_key = data["api_key"]
        object_type = data["object_type"]

        # Records are keyed by object_type in the payload (e.g. "create_board": [...]).
        records = data.get(object_type)
        if not records:
            raise ManagedError("Missing records parameter")

        args, selection = resolve_operation(object_type, api_key)
        if not args:
            raise ManagedError(f"Unsupported object type: {object_type}")

        # Build request variables + alias blocks per record. build_request_variables
        # also collects missing required fields in the same pass — we raise a clear
        # ManagedError instead of letting the request reach Monday.com.
        var_decls = []
        alias_blocks = []
        variables = {}

        for record_index, record in enumerate(records):
            record_var_decls, arg_strings, record_variables, missing = (
                build_request_variables(args, record, record_index)
            )
            if missing:
                raise ManagedError(f"{missing[0]} is required")
            var_decls.extend(record_var_decls)
            variables.update(record_variables)
            # Each record gets an alias (record_0, record_1, …) so all of them
            # run in one HTTP round-trip and results map back by index.
            alias_blocks.append(
                f"record_{record_index}: {object_type}({', '.join(arg_strings)}) {selection}".strip()
            )

        var_clause = f"({', '.join(var_decls)})" if var_decls else ""
        gql_operation = (
            f"{operation_keyword} {var_clause} {{ {' '.join(alias_blocks)} }}"
        )

        api_result = run_monday_query(
            query=gql_operation, token=api_key, variables=variables
        )

        # Map each aliased result back to its original record by index. Scalar
        # returns (e.g. update_board → JSON) come back raw, not a dict, so we
        # only spread when it's a dict. List returns are stored under
        # list_result_key when set; otherwise dropped.
        results = []
        for record_index in range(len(records)):
            result_data = api_result["data"].get(f"record_{record_index}")
            if result_data is None:
                raise ManagedError(f"No data returned for record {record_index + 1}")
            result_entry = {"success": True}
            if isinstance(result_data, dict):
                result_entry.update(result_data)
            elif isinstance(result_data, list) and list_result_key:
                result_entry[list_result_key] = result_data
            results.append(result_entry)

        return Response(
            data={"results": results},
            metadata={"affected_rows": len(results)},
        )
    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))
