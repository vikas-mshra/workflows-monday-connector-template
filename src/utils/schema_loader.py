import json

# workflows_cdk provides the core request/response abstractions and managed error handling
from workflows_cdk import ManagedError, Request, Response

# build_schema_from_args dynamically constructs field definitions from Monday.com introspection args
from src.monday_schema import build_schema_from_args


def build_schema_response(flask_request, schema_path, introspect_fn, label_fn, description_fn):
    """
    Builds and returns a dynamic schema response for a Monday.com connector endpoint.

    Loads a base JSON schema from disk, then — if the request contains a valid
    `api_key` and `object_type` — introspects Monday.com to append a dynamically
    generated array field (representing the selected object's columns/fields) to
    the schema before returning it.

    Args:
        flask_request:   The raw Flask request object.
        schema_path:     Path to the base JSON schema file on disk.
        introspect_fn:   Callable(object_type, api_key) → dict with an "args" key
                         containing Monday.com field metadata.
        label_fn:        Callable(object_type) → str label for the dynamic field.
        description_fn:  Callable(object_type) → str description for the dynamic field.

    Returns:
        Response: A CDK Response containing {"schema": <schema dict>}, or an
                  error Response if something goes wrong.
    """
    try:
        # Load the static base schema that defines the fixed form fields
        with open(schema_path) as f:
            base_schema = json.load(f)

        # Parse the incoming request using the CDK wrapper to normalise access to its data
        request = Request(flask_request)
        data = request.data

        # Extract user-submitted form values needed for dynamic schema generation
        form_data = data.get("form_data", {})
        api_key = form_data.get("api_key")
        object_type = form_data.get("object_type")  # e.g. "item", "board", etc.

        # If either required value is missing, return the base schema as-is (no dynamic fields)
        if not api_key or not object_type:
            return Response(data={"schema": base_schema})

        # Introspect Monday.com to retrieve the field arguments for the selected object type
        args = introspect_fn(object_type, api_key)["args"]

        # If introspection returns no args, fall back to the unmodified base schema
        if not args:
            return Response(data={"schema": base_schema})

        # Convert Monday.com field args into CDK-compatible field definitions and their display order
        fields, ui_order = build_schema_from_args(args, api_key)

        # Append the dynamically built array field to the base schema's field list
        base_schema["fields"].append(
            {
                "id": object_type,           # Field ID matches the selected object type
                "type": "array",             # Represented as a repeatable array of objects
                "label": label_fn(object_type),
                "description": description_fn(object_type),
                "default": [{}],             # Default to a single empty entry
                "items": {
                    "type": "object",
                    "default": {},
                    "fields": fields,                          # Dynamically built sub-fields
                    "ui_options": {"ui_order": ui_order},      # Control display order in the UI
                },
            }
        )

        return Response(data={"schema": base_schema})

    except ManagedError as e:
        # ManagedErrors are expected domain errors (e.g. bad API key, invalid object type)
        return Response.error(str(e))
    except Exception as e:
        # Catch-all for unexpected errors to avoid unhandled exceptions reaching the caller
        return Response.error(str(e))

