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

logger = logging.getLogger("monday.get_data")


def _resolve_get_operation(object_type: str, api_key: str) -> tuple:
    """
    Introspects the query arguments and selection fields for the given object type.

    Args:
        object_type: Name of the query field (e.g., 'items').
        api_key: The API Token (access token) for authentication.

    Returns:
        tuple: (args list, selection string/list of fields to fetch from Monday)
    """
    type_map = get_type_definitions(api_key)
    query_info = get_args_and_return_type("Query", object_type, type_map)
    return query_info["args"], parameter_to_fetch_from_monday(
        query_info["return_type"], type_map
    )


@router.route("/execute", methods=["GET", "POST"])
def execute():
    """
    Executes batched query operations.
    Loads credentials dynamically (supporting OAuth2 access token)
    and maps the record fields to GraphQL variables for batch query.
    """
    logger.info("Executing get_data batch operation")
    return execute_batched_operation(
        flask_request,
        resolve_operation=_resolve_get_operation,
        operation_keyword="query",
        list_result_key="data",
    )


@router.route("/content", methods=["GET", "POST"])
def content():
    """
    Fetches dynamic dropdown options (e.g., list of available queries).
    Extracts authentication credentials dynamically to execute the introspection.
    """
    logger.info("Fetching dynamic content for get_data")
    return build_content_data(
        flask_request,
        lambda fields: [
            {"value": f["name"], "label": humanize(f["name"])}
            for f in fields
            if len(f["args"]) > 0
            # Only include fields that accept arguments.
            # Fields without arguments (e.g. `account`) are excluded because
            # this UI is intended for parameterized query execution.
        ],
        gql_root_type="Query",
    )


@router.route("/schema", methods=["GET", "POST"])
def schema():
    """
    Generates the schema for the get action.
    Appends the dynamic GraphQL inputs for the selected query type.
    """
    logger.info("Retrieving schema for get_data")
    return build_schema_response(
        flask_request,
        Path(__file__).parent / "schema.json",
        "Query",
        lambda ot: f"{humanize(ot)} Records",
        lambda ot: f"List of {humanize(ot)} to retrieve",
    )
