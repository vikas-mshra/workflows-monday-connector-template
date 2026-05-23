import logging
from pathlib import Path

from flask import request as flask_request
from main import router
from src.utils.content_builder import build_content_data
from src.utils.execute.execute_utils import execute_batched_operation
from src.utils.graphql_type_definitions import get_mutation_field_definitions
from src.utils.helper import get_args_and_return_type, humanize
from src.utils.schema.schema_builder import build_schema_response

logger = logging.getLogger("monday.delete_data")


def _resolve_delete_operation(object_type: str, api_key: str) -> tuple:
    """
    Introspects the mutation arguments and selection fields for the given object type.

    Args:
        object_type: Name of the mutation field (e.g., 'delete_item').
        api_key: The API Token (access token) for authentication.

    Returns:
        tuple: (args list, selection string)
    """
    type_map = get_mutation_field_definitions(api_key)
    query_info = get_args_and_return_type("Mutation", object_type, type_map)
    return query_info["args"], "{ id }"


@router.route("/execute", methods=["GET", "POST"])
def execute():
    """
    Executes batched delete operations.
    Loads credentials dynamically (supporting OAuth2 access token)
    and maps the record fields to GraphQL variables for batch mutation.
    """
    logger.info("Executing delete_data batch operation")
    return execute_batched_operation(
        flask_request, resolve_operation=_resolve_delete_operation
    )


@router.route("/content", methods=["GET", "POST"])
def content():
    """
    Fetches dynamic dropdown options (e.g., list of available mutations starting with 'delete_' or 'remove_').
    Extracts authentication credentials dynamically to execute the introspection.
    """
    logger.info("Fetching dynamic content for delete_data")
    return build_content_data(
        flask_request,
        lambda fields: [
            {
                "value": f["name"],
                "label": humanize(f["name"]),
            }
            for f in fields
            if (f["name"].startswith("delete_") or f["name"].startswith("remove_"))
            and len(f["args"]) > 0
            # Only include fields that accept arguments.
            # Fields without arguments are excluded because this UI is intended for parameterized execution.
        ],
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    """
    Generates the schema for the delete action.
    Appends the dynamic GraphQL inputs for the selected mutation type.
    """
    logger.info("Retrieving schema for delete_data")
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Mutation",
        lambda ot: f"{humanize(ot)} ID",
        lambda ot: f"The ID of the {humanize(ot)} to delete",
    )
