import json
import re

from model1 import run_monday_query

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


def _object_field(name, label, description, object_name, required, token):
    # Introspect the INPUT_OBJECT type to discover its actual scalar fields,
    # the same way _enum_field fetches enum values dynamically.
    # This handles all input types (PaginationInput, ItemsQuery, WorkspacesQueryInput, etc.)
    # without any hardcoding.
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
            # Skip nested objects/enums — only render flat scalar inputs
            continue
        field_type = SCALAR_TYPE_MAP.get(f_scalar_name, "string")
        fields.append(
            {
                "id": f_name,
                "type": field_type,
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


def _gql_type_string(type_info):
    """Recursively converts introspection type info to a GQL declaration string."""
    if type_info["kind"] == "NON_NULL":
        return _gql_type_string(type_info["ofType"]) + "!"
    if type_info["kind"] == "LIST":
        return f"[{_gql_type_string(type_info['ofType'])}]"
    return type_info["name"]


def build_query_vars(args, record, index):
    s = str(index)
    var_decls, arg_strings, variables, missing_required = [], [], {}, []
    for arg in args:
        name = arg["name"]
        actual_kind, actual_name, required = _resolve_type(arg["type"])
        var_name = f"{name}_{s}"
        gql_type = _gql_type_string(arg["type"])
        if actual_kind == "LIST":
            item_key = name.rstrip("s")
            ids = [
                str(item[item_key])
                for item in (record.get(name) or [])
                if item.get(item_key)
            ]
            if not ids:
                if required:
                    missing_required.append(name)
                continue
            var_decls.append(f"${var_name}: {gql_type}")
            variables[var_name] = ids
            arg_strings.append(f"{name}: ${var_name}")
        else:
            value = record.get(name)
            if value is None:
                if required:
                    missing_required.append(name)
                continue
            if actual_kind == "SCALAR" and actual_name == "JSON":
                if isinstance(value, dict):
                    value = json.dumps(value)
                elif isinstance(value, str):
                    cleaned = re.sub(r",\s*([}\]])", r"\1", value)
                    json.loads(cleaned)
                    value = cleaned
            var_decls.append(f"${var_name}: {gql_type}")
            variables[var_name] = value
            arg_strings.append(f"{name}: ${var_name}")
    return var_decls, arg_strings, variables, missing_required


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
            field = _object_field(name, label, description, name, required, token)
        else:
            continue

        schema.append(field)
        ui_order.append(name)

    return schema, ui_order
