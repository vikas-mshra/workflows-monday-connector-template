from src.monday_client import run_monday_query

# Maps Monday.com GraphQL scalar type names to Stacksync field type strings.
SCALAR_TYPE_MAP = {
    "String": "string",
    "Boolean": "boolean",
    "ID": "integer",
    "Int": "integer",
    "JSON": "string",
    "ISO8601DateTime": "string",
}

# Extra UI hints keyed by Monday.com scalar type name.
# JSON fields get a code editor widget so the user can enter structured data.
SCALAR_UI_OPTIONS_MAP = {
    "JSON": {
        "ui_widget": "CodeblockWidget",
        "ui_options": {"language": "json"},
    },
}


def humanize(name: str) -> str:
    """Converts a snake_case identifier to a Title Case human label."""
    return name.replace("_", " ").title()


def _resolve_type(type_info: dict) -> tuple:
    """
    Unwraps one level of NON_NULL and returns (kind, name, required).

    GraphQL marks required args as NON_NULL(actualType). We peel that wrapper
    so callers can work with the real kind/name while still knowing it's required.
    """
    if type_info["kind"] == "NON_NULL":
        of_type = type_info.get("ofType") or {}
        return of_type.get("kind"), of_type.get("name"), True
    return type_info["kind"], type_info.get("name"), False


def _enum_field(name, label, description, enum_name, required, token) -> dict:
    """
    Builds a SelectWidget field by fetching the enum's values via introspection.
    Always queries the API so new enum members appear automatically.
    """
    query = f"""
        query {{
            __type(name: "{enum_name}") {{
                name
                enumValues {{ name }}
            }}
        }}
    """
    result = run_monday_query(query=query, token=token)
    enum_values = result["data"]["__type"]["enumValues"]

    return {
        "id": name,
        "type": "string",
        "label": label,
        "description": description,
        "validation": {"required": required},
        "choices": {
            "values": [
                {"value": v["name"], "label": humanize(v["name"])} for v in enum_values
            ]
        },
        "ui_options": {"ui_widget": "SelectWidget"},
    }


def _scalar_field(name, label, description, scalar_name, required) -> dict:
    """Builds a plain input field for a GraphQL scalar arg."""
    field_type = SCALAR_TYPE_MAP.get(scalar_name, "string")
    field = {
        "id": name,
        "type": field_type,
        "label": label,
        "description": description,
        "validation": {"required": required},
    }
    ui_options = SCALAR_UI_OPTIONS_MAP.get(scalar_name)
    if ui_options:
        field["ui_options"] = ui_options
    return field


def _array_field(name, label, description, required) -> dict:
    """Builds a repeatable list field for a GraphQL LIST arg."""
    item_name = name.rstrip("s")
    return {
        "id": name,
        "type": "array",
        "label": label,
        "description": description,
        "default": [{}],
        "items": {
            "type": "object",
            "default": {},
            "fields": [
                {
                    "id": item_name,
                    "type": "string",
                    "label": humanize(item_name),
                    "description": description.rstrip("s") if description else "",
                    "validation": {"required": False},
                }
            ],
            "ui_options": {"ui_order": [item_name]},
        },
        "validation": {"min_items": 1} if required else {},
    }


def _object_field(name, label, description, object_name, required, token) -> dict:
    """
    Builds a grouped object field for a GraphQL INPUT_OBJECT arg.

    Introspects the input type's fields dynamically so this works for any
    INPUT_OBJECT without hardcoding — PaginationInput, ItemsQuery, etc.
    Only flat SCALAR sub-fields are rendered; nested objects/enums are skipped.
    """
    query = f"""
        query {{
            __type(name: "{object_name}") {{
                inputFields {{
                    name
                    description
                    type {{
                        name
                        kind
                        ofType {{ name kind }}
                    }}
                }}
            }}
        }}
    """
    result = run_monday_query(query=query, token=token)
    input_fields = (result["data"]["__type"] or {}).get("inputFields") or []

    fields = []
    ui_order = []
    for f in input_fields:
        f_name = f["name"]
        f_kind, f_scalar_name, f_required = _resolve_type(f["type"])
        if f_kind != "SCALAR":
            continue
        fields.append(
            {
                "id": f_name,
                "type": SCALAR_TYPE_MAP.get(f_scalar_name, "string"),
                "label": humanize(f_name),
                "description": f.get("description", ""),
                "validation": {"required": f_required},
            }
        )
        ui_order.append(f_name)

    return {
        "id": name,
        "type": "object",
        "label": label,
        "description": description,
        "fields": fields,
        "ui_options": {"ui_order": ui_order},
        "validation": {"required": required},
    }


def build_schema_from_args(args: list, token: str) -> tuple:
    """
    Converts a list of GraphQL arg definitions (from introspection) into
    Stacksync form field definitions and a ui_order list.

    Returns (fields, ui_order) ready to drop into a schema response.
    """
    schema = []
    ui_order = []
    for arg in args:
        name = arg["name"]
        label = humanize(name)
        description = arg.get("description", "")
        actual_kind, actual_name, required = _resolve_type(arg["type"])

        if actual_kind == "ENUM":
            field = _enum_field(name, label, description, actual_name, required, token)
        elif actual_kind == "SCALAR":
            field = _scalar_field(name, label, description, actual_name, required)
        elif actual_kind == "LIST":
            field = _array_field(name, label, description, required)
        elif actual_kind == "INPUT_OBJECT":
            field = _object_field(name, label, description, name, required, token)
        else:
            continue

        schema.append(field)
        ui_order.append(name)

    return schema, ui_order
