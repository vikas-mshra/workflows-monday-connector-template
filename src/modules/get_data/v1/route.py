from pathlib import Path

from flask import request as flask_request

from main import router
from src.monday_client import get_args_and_return_type, get_type_definitions
from src.monday_content import build_content_response
from src.monday_schema import build_response_selection, humanize
from src.utils.execute_runner import execute_batched_operation
from src.utils.schema_loader import build_schema_response


def _resolve_get_operation(object_type: str, api_key: str) -> tuple:
    type_map = get_type_definitions(api_key)
    query_info = get_args_and_return_type("Query", object_type, type_map)
    return query_info["args"], build_response_selection(
        query_info["return_type"], type_map
    )


@router.route("/execute", methods=["GET", "POST"])
def execute():
    return execute_batched_operation(
        flask_request,
        resolve_operation=_resolve_get_operation,
        operation_keyword="query",
        list_result_key="data",
    )


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
