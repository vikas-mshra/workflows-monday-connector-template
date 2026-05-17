from pathlib import Path

from flask import request as flask_request

from main import router
from src.monday_client import get_mutation_args
from src.monday_content import build_content_response
from src.monday_schema import humanize
from src.utils.execute_runner import execute_batched_operation
from src.utils.schema_loader import build_schema_response


def _resolve_delete_operation(object_type: str, api_key: str) -> tuple:
    mutation_info = get_mutation_args(object_type, api_key)
    return_type = mutation_info["return_type"]
    base_return_kind = (return_type.get("ofType") or return_type).get("kind")
    selection = "" if base_return_kind in ("SCALAR", "ENUM") else "{ id }"
    return mutation_info["args"], selection


@router.route("/execute", methods=["GET", "POST"])
def execute():
    return execute_batched_operation(
        flask_request, resolve_operation=_resolve_delete_operation
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
