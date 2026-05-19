from pathlib import Path

from flask import request as flask_request

from main import router
from src.utils.graphql_type_definitions import (
    get_args_and_return_type,
    get_type_definitions,
)
from src.utils.content_builder import build_content_data
from src.utils.execute.execute_helper import parameter_to_fetch_from_monday
from src.utils.execute.execute_utils import execute_batched_operation
from src.utils.schema.schema_builder import build_schema_response
from src.utils.utils import humanize


def _resolve_duplicate_operation(object_type: str, api_key: str) -> tuple:
    field_map = get_type_definitions(api_key)
    mutation_info = get_args_and_return_type("Mutation", object_type, field_map)
    return mutation_info["args"], parameter_to_fetch_from_monday(
        mutation_info["return_type"], field_map
    )


@router.route("/execute", methods=["GET", "POST"])
def execute():
    return execute_batched_operation(
        flask_request, resolve_operation=_resolve_duplicate_operation
    )


@router.route("/content", methods=["GET", "POST"])
def content():
    return build_content_data(
        flask_request,
        lambda fields: [
            {
                "value": f["name"],
                "label": humanize(f["name"].removeprefix("duplicate_")),
            }
            for f in fields
            if f["name"].startswith("duplicate_")
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
