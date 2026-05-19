import json

# Maps Monday.com GraphQL scalar type names to Stacksync field type strings.
SCALAR_TYPE_MAP = {
    "String": "string",
    "Boolean": "boolean",
    "ID": "string",
    "Int": "integer",
    "Float": "string",
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


def _extract_inner_type(type_info: dict) -> tuple:
    """
    Unwraps one level of NON_NULL and returns (kind, name, required).

    GraphQL marks required args as NON_NULL(actualType). We peel that wrapper
    so callers can work with the real kind/name while still knowing it's required.
    """
    if type_info["kind"] == "NON_NULL":
        of_type = type_info.get("ofType") or {}
        return of_type.get("kind"), of_type.get("name"), True
    return type_info["kind"], type_info.get("name"), False


def _unwrap_non_null_fully(type_info: dict) -> tuple:
    """
    Fully unwraps all NON_NULL wrappers, returning (inner_type_dict, required).

    Unlike _extract_inner_type (which peels exactly one layer and returns only kind/name),
    this returns the actual type dict so callers can continue walking ofType — necessary
    for stacked wrappers like NON_NULL(LIST(NON_NULL(INPUT_OBJECT))).
    """
    required = False
    current_type = type_info
    while current_type and current_type.get("kind") == "NON_NULL":
        required = True
        current_type = current_type.get("ofType") or {}
    return current_type, required


def _build_enum_field(
    name, label, description, enum_name, required, type_map: dict, default_value=None
) -> dict:
    """
    Builds a SelectWidget field by reading the enum's values from type_map.
    type_map is built once per /schema request from a single __schema API call.
    """
    enum_values = (type_map.get(enum_name) or {}).get("enumValues") or []

    field = {
        "id": name,
        "type": "string",
        "label": label,
        "choices": {
            "values": [
                {"value": v["name"], "label": humanize(v["name"])} for v in enum_values
            ]
        },
        "ui_options": {"ui_widget": "SelectWidget"},
        "validation": {"pattern": ".*", "required": True}
        if required
        else {"pattern": ".*"},
    }

    # making sure the default value is in the enum values
    if default_value and default_value in [v["name"] for v in enum_values]:
        field["default"] = default_value

    if description:
        field["description"] = description
    return field


def _build_scalar_field(
    name, label, description, scalar_name, required, default_value=None
) -> dict:
    """Builds a plain input field for a GraphQL scalar arg."""
    field_type = SCALAR_TYPE_MAP.get(scalar_name, "string")
    field = {
        "id": name,
        "type": field_type,
        "label": label,
        "default": "",
    }
    if default_value is not None:
        try:
            field["default"] = json.loads(default_value)
        except (json.JSONDecodeError, ValueError):
            field["default"] = default_value
    if description:
        field["description"] = description
    if required:
        field["validation"] = {"required": True}
    ui_options = SCALAR_UI_OPTIONS_MAP.get(scalar_name)
    if ui_options:
        field["ui_options"] = ui_options
    return field


def _build_array_field(
    name, label, description, required, item_fields=None, item_ui_order=None
) -> dict:
    """Builds a repeatable list field for a GraphQL LIST arg.

    Pass item_fields + item_ui_order to get typed items (e.g. for LIST(INPUT_OBJECT)).
    When omitted, falls back to a single generic string item whose id matches the
    arg name — the request-side LIST(SCALAR/ENUM) reader looks it up by the same key.
    """
    if item_fields is None:
        item_field = {
            "id": name,
            "type": "string",
            "label": humanize(name),
            "default": "",
        }
        if description:
            item_field["description"] = description
        item_fields = [item_field]
        item_ui_order = [name]

    field = {
        "id": name,
        "type": "array",
        "label": label,
        "default": [{}] if required else [],
        "items": {
            "type": "object",
            "default": {},
            "ui_options": {"ui_order": item_ui_order},
            "fields": item_fields,
        },
        "validation": {"required": True, "min_items": 1}
        if required
        else {"required": False, "min_items": 0},
    }
    if description:
        field["description"] = description
    return field


def _build_object_field(
    name, label, description, object_name, required, type_map: dict, visited=None
) -> dict:
    """
    Builds a grouped object field for a GraphQL INPUT_OBJECT arg.

    Reads the input type's fields from type_map instead of calling the API.
    Handles SCALAR, ENUM, LIST, and nested INPUT_OBJECT sub-fields. Cycle
    detection via `visited` prevents infinite recursion on self-referential
    types like ItemsQueryGroup.
    """
    # | creates a new set per call; .add() would mutate the shared set and cause
    # sibling branches to incorrectly skip types they haven't visited yet.
    visited = (visited or set()) | {object_name}

    input_fields = (type_map.get(object_name) or {}).get("inputFields") or []

    fields = []
    ui_order = []
    for input_field in input_fields:
        field_name = input_field["name"]
        field_label = humanize(field_name)
        field_description = input_field.get("description") or ""
        field_default_value = input_field.get("defaultValue")
        field_type_info, field_required = _unwrap_non_null_fully(input_field["type"])
        # If the parent object is optional, its sub-fields are only required when
        # the parent is actually provided — not enforced in the UI.
        if not required:
            field_required = False
        field_kind = field_type_info.get("kind")
        field_type_name = field_type_info.get("name")

        if field_kind == "SCALAR":
            sub_field = _build_scalar_field(
                field_name,
                field_label,
                field_description,
                field_type_name,
                field_required,
                field_default_value,
            )
        elif field_kind == "ENUM":
            sub_field = _build_enum_field(
                field_name,
                field_label,
                field_description,
                field_type_name,
                field_required,
                type_map,
                field_default_value,
            )
        elif field_kind == "LIST":
            element_type, _ = _unwrap_non_null_fully(
                field_type_info.get("ofType") or {}
            )
            element_kind = element_type.get("kind")
            element_type_name = element_type.get("name")
            # Guard against self-referential lists (e.g. ItemsQueryGroup.groups -> ItemsQueryGroup).
            if element_kind == "INPUT_OBJECT" and element_type_name not in visited:
                nested = _build_object_field(
                    field_name,
                    field_label,
                    field_description,
                    element_type_name,
                    False,
                    type_map,
                    visited,
                )
                sub_field = _build_array_field(
                    field_name,
                    field_label,
                    field_description,
                    field_required,
                    item_fields=nested["fields"],
                    item_ui_order=nested["ui_options"]["ui_order"],
                )
            elif element_kind == "ENUM" and element_type_name:
                item_field = _build_enum_field(
                    field_name,
                    humanize(field_name),
                    field_description,
                    element_type_name,
                    False,
                    type_map,
                )
                sub_field = _build_array_field(
                    field_name,
                    field_label,
                    field_description,
                    field_required,
                    item_fields=[item_field],
                    item_ui_order=[field_name],
                )
            else:
                sub_field = _build_array_field(
                    field_name, field_label, field_description, field_required
                )
        elif field_kind == "INPUT_OBJECT":
            if field_type_name in visited:
                continue
            sub_field = _build_object_field(
                field_name,
                field_label,
                field_description,
                field_type_name,
                field_required,
                type_map,
                visited,
            )
        else:
            continue

        fields.append(sub_field)
        ui_order.append(field_name)

    field = {
        "id": name,
        "type": "object",
        "label": label,
        "default": {},
        "fields": fields,
        "ui_options": {"ui_order": ui_order},
    }
    if description:
        field["description"] = description
    return field


def build_schema_from_object_args(args: list, type_map: dict) -> tuple:
    """
    Converts a list of GraphQL arg definitions (from introspection) into
    Stacksync form field definitions and a ui_order list.

    type_map is the {name: type_def} dict built from a single __schema call —
    all enum and input object lookups resolve from it with no further API calls.

    Returns (fields, ui_order) ready to drop into a schema response.
    """
    schema = []
    ui_order = []
    for arg in args:
        name = arg["name"]
        label = humanize(name)
        description = arg.get("description", "")
        default_value = arg.get("defaultValue")
        actual_kind, actual_name, required = _extract_inner_type(arg["type"])

        if actual_kind == "ENUM":
            field = _build_enum_field(
                name, label, description, actual_name, required, type_map, default_value
            )
        elif actual_kind == "SCALAR":
            field = _build_scalar_field(
                name, label, description, actual_name, required, default_value
            )
        elif actual_kind == "LIST":
            # _extract_inner_type discards the type dict; re-peel to get the LIST node
            # so we can walk into its ofType and identify the element type.
            unwrapped_type, _ = _unwrap_non_null_fully(arg["type"])
            element_type, _ = _unwrap_non_null_fully(unwrapped_type.get("ofType") or {})
            element_kind = element_type.get("kind")
            element_type_name = element_type.get("name")
            if element_kind == "INPUT_OBJECT":
                nested = _build_object_field(
                    name, label, description, element_type_name, False, type_map
                )
                field = _build_array_field(
                    name,
                    label,
                    description,
                    required,
                    item_fields=nested["fields"],
                    item_ui_order=nested["ui_options"]["ui_order"],
                )
            elif element_kind == "ENUM" and element_type_name:
                item_field = _build_enum_field(
                    name,
                    humanize(name),
                    description,
                    element_type_name,
                    False,
                    type_map,
                )
                field = _build_array_field(
                    name,
                    label,
                    description,
                    required,
                    item_fields=[item_field],
                    item_ui_order=[name],
                )
            else:
                field = _build_array_field(name, label, description, required)
        elif actual_kind == "INPUT_OBJECT":
            field = _build_object_field(
                name, label, description, actual_name, required, type_map
            )
        else:
            continue

        schema.append(field)
        ui_order.append(name)

    return schema, ui_order
