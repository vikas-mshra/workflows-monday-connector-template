from pathlib import Path

from flask import request as flask_request

from main import router
from src.monday_client import get_args_and_return_type, get_mutation_field_definitions
from src.monday_content import build_content_response
from src.monday_schema import humanize
from src.utils.execute_runner import execute_batched_operation
from src.utils.schema_loader import build_schema_response


def _resolve_update_operation(object_type: str, api_key: str) -> tuple:
    field_map = get_mutation_field_definitions(api_key)
    query_info = get_args_and_return_type("Mutation", object_type, field_map)
    return_type = query_info["return_type"]
    base_return_kind = (return_type.get("ofType") or return_type).get("kind")
    selection = "" if base_return_kind in ("SCALAR", "ENUM") else "{ id }"
    return query_info["args"], selection


@router.route("/execute", methods=["GET", "POST"])
def execute():
    return execute_batched_operation(
        flask_request, resolve_operation=_resolve_update_operation
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
            if (
                f["name"].startswith("update_")
                or f["name"].startswith("batch_")
                or f["name"].startswith("edit_")
                or (f["name"].startswith("change_") and "column" in f["name"])
            )
        ],
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Mutation",
        humanize,
        lambda ot: f"List of {humanize(ot)} to update/edit",
    )
