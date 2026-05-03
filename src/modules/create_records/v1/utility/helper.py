from model import run_monday_query

SCALAR_TYPE_MAP = {
    "String": "string",
    "Boolean": "boolean",
    "ID": "integer",
    "JSON": "string",
}

SCALAR_UI_OPTIONS_MAP = {
    "JSON": {
        "ui_widget": "CodeblockWidget",
        "ui_options": {"language": "json"},
    },
}


def humanize(name):
    return name.replace("_", " ").title()


def _resolve_type(type_info):
    """Returns (actual_kind, actual_name, required)."""
    if type_info["kind"] == "NON_NULL":
        of_type = type_info.get("ofType") or {}
        return of_type.get("kind"), of_type.get("name"), True
    return type_info["kind"], type_info.get("name"), False


def _enum_field(name, label, description, enum_name, required, token):
    query = f"""
        query {{
            __type(name: "{enum_name}") {{
                name
                enumValues {{
                    name
                }}
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


def _scalar_field(name, label, description, scalar_name, required):
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


def _array_field(name, label, description, required):
    item_name = name.rstrip("s")
    item_label = humanize(item_name)
    item_description = description.rstrip("s") if description else ""
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
                    "label": item_label,
                    "description": item_description,
                    "validation": {"required": False},
                }
            ],
            "ui_options": {"ui_order": [item_name]},
        },
        "validation": {"min_items": 1} if required else {},
    }


def _object_field(name, label, description, required):
    return {
        "id": name,
        "type": "object",
        "label": label,
        "description": description,
        "fields": [
            {
                "id": "preset_type",
                "type": "string",
                "label": "Preset Type",
                "description": "The preset type for item nickname",
                "validation": {"required": False},
            },
            {
                "id": "singular",
                "type": "string",
                "label": "Singular",
                "description": "The singular form of the item nickname",
                "validation": {"required": False},
            },
            {
                "id": "plural",
                "type": "string",
                "label": "Plural",
                "description": "The plural form of the item nickname",
                "validation": {"required": False},
            },
        ],
        "ui_options": {"ui_order": ["preset_type", "singular", "plural"]},
        "validation": {"required": required},
    }


def build_schema_from_args(args, token):
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
            field = _object_field(name, label, description, required)
        else:
            continue

        schema.append(field)
        ui_order.append(name)

    return schema, ui_order