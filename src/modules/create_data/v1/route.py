import logging
from pathlib import Path

from flask import request as flask_request
from main import router
from src.utils.content_builder import build_content_data
from src.utils.execute.execute_utils import execute_batched_operation
from src.utils.graphql_type_definitions import get_mutation_field_definitions
from src.utils.helper import get_args_and_return_type, humanize
from src.utils.schema.schema_builder import build_schema_response

logger = logging.getLogger("monday.create_data")


def _resolve_create_operation(object_type: str, api_key: str) -> tuple:
    """
    Introspects the mutation arguments and selection fields for the given object type.

    Args:
        object_type: Name of the mutation field (e.g., 'create_item').
        api_key: The API Token (access token) for authentication.

    Returns:
        tuple: (args list, selection string)
    """
    field_map = get_mutation_field_definitions(api_key)
    query_info = get_args_and_return_type("Mutation", object_type, field_map)
    return query_info["args"], "{ id }"


@router.route("/execute", methods=["GET", "POST"])
def execute():
    """
    Executes batched create operations.
    Loads credentials dynamically (supporting OAuth2 access token)
    and maps the record fields to GraphQL variables for batch mutation.
    """
    logger.info("Executing create_data batch operation")
    return execute_batched_operation(
        flask_request, resolve_operation=_resolve_create_operation
    )


@router.route("/content", methods=["GET", "POST"])
def content():
    """
    Fetches dynamic dropdown options (e.g., list of available mutations).
    Extracts authentication credentials dynamically to execute the introspection.
    """
    logger.info("Fetching dynamic content for create_data")
    return build_content_data(
        flask_request,
        lambda fields: [
            {
                "value": f["name"],
                "label": humanize(
                    f["name"].removeprefix("create_").removeprefix("or_get_")
                    # to exclude create_or_get_tag option in the dropdown
                ),
            }
            for f in fields
            if f["name"].startswith("create_")
        ],
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    """
    Generates the schema for the create action.
    Appends the dynamic GraphQL inputs for the selected mutation type.
    """
    logger.info("Retrieving schema for create_data")
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Mutation",
        lambda ot: f"{humanize(ot)} Records",
        lambda ot: f"List of {humanize(ot)} to create",
    )
