from pathlib import Path

from flask import request as flask_request

from main import router
from src.monday_client import get_args_and_return_type, get_type_definitions
from src.monday_content import build_content_response
from src.monday_schema import parameter_to_fetch_from_monday, humanize
from src.utils.execute_runner import execute_batched_operation
from src.utils.schema_loader import build_schema_response


def _resolve_add_operation(object_type: str, api_key: str) -> tuple:
    type_map = get_type_definitions(api_key)
    mutation_info = get_args_and_return_type("Mutation", object_type, type_map)
    return mutation_info["args"], parameter_to_fetch_from_monday(
        mutation_info["return_type"], type_map
    )


@router.route("/execute", methods=["GET", "POST"])
def execute():
    return execute_batched_operation(
        flask_request,
        resolve_operation=_resolve_add_operation,
        list_result_key="items",
    )


@router.route("/content", methods=["GET", "POST"])
def content():
    return build_content_response(
        flask_request,
        lambda fields: [
            {
                "value": f["name"],
                "label": humanize(f["name"]),
            }
            for f in fields
            if f["name"].startswith("add_") and not f["name"].startswith("add_file")
        ],
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Mutation",
        humanize,
        lambda ot: f"List of {humanize(ot)}",
    )
