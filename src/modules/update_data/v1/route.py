import logging
from pathlib import Path

from flask import request as flask_request
from main import router
from src.utils.content_builder import build_content_data
from src.utils.execute.execute_utils import execute_batched_operation
from src.utils.graphql_type_definitions import get_mutation_field_definitions
from src.utils.helper import get_args_and_return_type, humanize
from src.utils.schema.schema_builder import build_schema_response

logger = logging.getLogger("monday.update_data")


def _resolve_update_operation(object_type: str, api_key: str) -> tuple:
    """
    Introspects the mutation arguments and selection fields for the given object type.

    Args:
        object_type: Name of the mutation field (e.g., 'change_simple_column_value').
        api_key: The API Token (access token) for authentication.

    Returns:
        tuple: (args list, selection string)
    """
    field_map = get_mutation_field_definitions(api_key)
    query_info = get_args_and_return_type("Mutation", object_type, field_map)
    return_type = query_info["return_type"]
    base_return_kind = (return_type.get("ofType") or return_type).get("kind")
    selection = "" if base_return_kind in ("SCALAR", "ENUM") else "{ id }"
    return query_info["args"], selection


@router.route("/execute", methods=["GET", "POST"])
def execute():
    """
    Executes batched update operations.
    Loads credentials dynamically (supporting OAuth2 access token)
    and maps the record fields to GraphQL variables for batch mutation.
    """
    logger.info("Executing update_data batch operation")
    return execute_batched_operation(
        flask_request, resolve_operation=_resolve_update_operation
    )


@router.route("/content", methods=["GET", "POST"])
def content():
    """
    Fetches dynamic dropdown options (e.g., list of available mutations starting with 'update_', 'batch_', 'edit_', or 'change_').
    Extracts authentication credentials dynamically to execute the introspection.
    """
    logger.info("Fetching dynamic content for update_data")
    return build_content_data(
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
                # to not include change_item_position and only include that starts with change_ and contains column in its mutation function name.
                # TODO: Check if the last condition can be removed to include change_item_position as well.
            )
            and len(f["args"]) > 0
            # Only include fields that accept arguments.
            # Fields without arguments are excluded because this UI is intended for parameterized execution.
        ],
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    """
    Generates the schema for the update action.
    Appends the dynamic GraphQL inputs for the selected mutation type.
    """
    logger.info("Retrieving schema for update_data")
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Mutation",
        humanize,
        lambda ot: f"List of {humanize(ot)} to update/edit",
    )
