import json
import logging

from src.utils.content_builder import get_credentials
from src.utils.graphql_type_definitions import get_type_definitions
from src.utils.helper import get_args_and_return_type, validate_object_type
from src.utils.schema.schema_loader import build_schema_from_object_args
from workflows_cdk import ManagedError, Request, Response

logger = logging.getLogger("monday.schema_builder")


def build_schema_response(
    flask_request, schema_path, gql_root_type, label_fn, description_fn
):
    """
    Builds and returns a dynamic schema response for a Monday.com connector endpoint.

    Loads a base JSON schema from disk, then — if the request contains a valid
    `api_key` and `object_type` — makes a single __schema introspection call to
    build a type map, resolves the selected object's args from that map, converts
    them to Stacksync field definitions, and appends a dynamic array field to the
    schema before returning it.

    Args:
        flask_request:  The raw Flask request object.
        schema_path:    Path to the base JSON schema file on disk.
        gql_root_type:  "Mutation" or "Query" — which root type to look up args from.
        label_fn:       Callable(object_type) → str label for the dynamic field.
        description_fn: Callable(object_type) → str description for the dynamic field.

    Returns:
        Response: A CDK Response containing {"schema": <schema dict>}, or an
                  error Response if something goes wrong.
    """
    object_type = None
    try:
        # Load the static base schema that defines the fixed form fields
        with open(schema_path) as f:
            base_schema = json.load(f)

        # Parse the incoming request using the CDK wrapper to normalise access to its data
        request = Request(flask_request)
        data = request.data

        try:
            credentials = get_credentials(flask_request)
        except ManagedError as e:
            logger.warning(
                "No credentials available for schema building: %s",
                e,
                exc_info=True,
            )
            return Response(data={"schema": base_schema})

        api_key = credentials.get("access_token")

        # Extract user-submitted form values needed for dynamic schema generation
        form_data = data.get("form_data", {})
        object_type = form_data.get("object_type")  # e.g. "item", "board", etc.

        # If either required value is missing, return the base schema as-is (no dynamic fields)
        if not api_key or not object_type:
            return Response(data={"schema": base_schema})

        validate_object_type(object_type)

        # One __schema call fetches every type in Monday.com's schema at once.
        # All subsequent lookups (enum values, input fields, return type fields)
        # read from this map — no further API calls during /schema.
        type_map = get_type_definitions(api_key)

        args = get_args_and_return_type(gql_root_type, object_type, type_map)["args"]

        if not args:
            return Response(data={"schema": base_schema})

        # Convert Monday.com field args into CDK-compatible field definitions and their display order
        fields, ui_order = build_schema_from_object_args(args, type_map)

        # Append the dynamically built array field to the base schema's field list
        base_schema["fields"].append(
            {
                "id": object_type,  # Field ID matches the selected object type
                "type": "array",  # Represented as a repeatable array of objects
                "label": label_fn(object_type),
                "description": description_fn(object_type),
                "default": [{}],  # Default to a single empty entry
                "items": {
                    "type": "object",
                    "default": {},
                    "fields": fields,  # Dynamically built sub-fields
                    "ui_options": {
                        "ui_order": ui_order
                    },  # Control display order in the UI
                },
            }
        )

        return Response(data={"schema": base_schema})

    except ManagedError:
        raise
    except Exception as e:
        logger.exception(
            "Unexpected schema building error for object_type=%s",
            object_type,
        )
        status_code = getattr(e, "status_code", 500)
        raise ManagedError(
            error="Failed to build schema", status_code=status_code
        ) from e
