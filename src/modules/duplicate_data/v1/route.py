import logging
from pathlib import Path

from flask import request as flask_request
from main import router
from src.utils.content_builder import build_content_data
from src.utils.execute.execute_helper import parameter_to_fetch_from_monday
from src.utils.execute.execute_utils import execute_batched_operation
from src.utils.graphql_type_definitions import get_type_definitions
from src.utils.helper import get_args_and_return_type, humanize
from src.utils.schema.schema_builder import build_schema_response

logger = logging.getLogger("monday.duplicate_data")


def _resolve_duplicate_operation(object_type: str, api_key: str) -> tuple:
    """
    Introspects the mutation arguments and selection fields for the given object type.

    Args:
        object_type: Name of the mutation field (e.g., 'duplicate_group').
        api_key: The API Token (access token) for authentication.

    Returns:
        tuple: (args list, selection string/list of fields to fetch from Monday)
    """
    field_map = get_type_definitions(api_key)
    mutation_info = get_args_and_return_type("Mutation", object_type, field_map)
    return mutation_info["args"], parameter_to_fetch_from_monday(
        mutation_info["return_type"], field_map
    )


@router.route("/execute", methods=["GET", "POST"])
def execute():
    """
    Executes batched duplicate operations.
    Loads credentials dynamically (supporting OAuth2 access token)
    and maps the record fields to GraphQL variables for batch mutation.
    """
    logger.info("Executing duplicate_data batch operation")
    return execute_batched_operation(
        flask_request, resolve_operation=_resolve_duplicate_operation
    )


@router.route("/content", methods=["GET", "POST"])
def content():
    """
    Fetches dynamic dropdown options (e.g., list of available mutations starting with 'duplicate_').
    Extracts authentication credentials dynamically to execute the introspection.
    """
    logger.info("Fetching dynamic content for duplicate_data")
    return build_content_data(
        flask_request,
        lambda fields: [
            {
                "value": f["name"],
                "label": humanize(f["name"].removeprefix("duplicate_")),
            }
            for f in fields
            if f["name"].startswith("duplicate_") and len(f["args"]) > 0
            # Only include fields that accept arguments.
            # Fields without arguments are excluded because this UI is intended for parameterized execution.
        ],
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    """
    Generates the schema for the duplicate action.
    Appends the dynamic GraphQL inputs for the selected mutation type.
    """
    logger.info("Retrieving schema for duplicate_data")
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Mutation",
        humanize,
        lambda ot: f"List of {humanize(ot)}",
    )
