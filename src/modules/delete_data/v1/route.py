from pathlib import Path

from flask import request as flask_request

from main import router
from src.utils.content_builder import build_content_data
from src.utils.execute.execute_utils import execute_batched_operation
from src.utils.graphql_type_definitions import get_mutation_field_definitions
from src.utils.helper import get_args_and_return_type, humanize
from src.utils.schema.schema_builder import build_schema_response


def _resolve_delete_operation(object_type: str, api_key: str) -> tuple:
    type_map = get_mutation_field_definitions(api_key)
    query_info = get_args_and_return_type("Mutation", object_type, type_map)
    return query_info["args"], "{ id }"


@router.route("/execute", methods=["GET", "POST"])
def execute():
    return execute_batched_operation(
        flask_request, resolve_operation=_resolve_delete_operation
    )


@router.route("/content", methods=["GET", "POST"])
def content():
    return build_content_data(
        flask_request,
        lambda fields: [
            {
                "value": f["name"],
                "label": humanize(f["name"]),
            }
            for f in fields
            if f["name"].startswith("delete_") or f["name"].startswith("remove_")
        ],
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Mutation",
        lambda ot: f"{humanize(ot)} ID",
        lambda ot: f"The ID of the {humanize(ot)} to delete",
    )
