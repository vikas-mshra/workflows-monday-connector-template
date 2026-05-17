import json
import re

from ._schema_fields import _extract_inner_type


def _gql_type_string(type_info: dict) -> str:
    """Recursively converts introspection type info to a GQL type declaration string."""
    if type_info["kind"] == "NON_NULL":
        return _gql_type_string(type_info["ofType"]) + "!"
    if type_info["kind"] == "LIST":
        return f"[{_gql_type_string(type_info['ofType'])}]"
    return type_info["name"]


def _is_empty_input(value) -> bool:
    """True if a value should be omitted: None, empty string, empty dict, or a dict
    whose values are all recursively empty. Prevents passing {} or {"sub": {}} for
    INPUT_OBJECT args, which Monday.com rejects with VALIDATION_INVALID_TYPE_VARIABLE."""
    if value is None or value == "":
        return True
    if isinstance(value, dict):
        return not value or all(_is_empty_input(v) for v in value.values())
    return False


def _build_operation_variables(args: list, record: dict, index: int) -> tuple:
    """
    Shared core for build_mutation_vars and build_query_vars.

    Walks the introspection args for one record and returns
    (var_decls, arg_strings, variables, missing_required) ready to splice
    into a batched GQL operation. Collecting missing-required names in the
    same pass is free (we're already iterating) and gives the user a clear
    `"<field> is required"` error instead of Monday.com's GraphQL error.
    """
    index_suffix = str(index)
    var_decls = []
    arg_strings = []
    variables = {}
    missing_required = []

    for arg in args:
        name = arg["name"]
        actual_kind, actual_name, required = _extract_inner_type(arg["type"])
        var_name = f"{name}_{index_suffix}"
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
            # INPUT_OBJECT args with all-empty sub-fields (e.g. {"calculated": {}})
            # fail Monday.com's type validation — omit them entirely.
            if actual_kind == "INPUT_OBJECT" and _is_empty_input(value):
                if required:
                    missing_required.append(name)
                continue
            # An empty string from the form means the user left the field blank — skip it.
            if actual_kind == "SCALAR" and value == "":
                if required:
                    missing_required.append(name)
                continue
            # Monday.com's JSON scalar expects a JSON string (not a parsed object).
            # If the value is a dict (e.g. sent as an object from the form), stringify it.
            # If it's already a string (from CodeblockWidget), strip trailing commas
            # so Monday.com's parser accepts it.
            if actual_kind == "SCALAR" and actual_name == "JSON":
                if isinstance(value, dict):
                    value = json.dumps(value)
                elif isinstance(value, str):
                    cleaned = re.sub(r",\s*([}\]])", r"\1", value)
                    json.loads(cleaned)  # validate only; raise on malformed JSON
                    value = cleaned
            var_decls.append(f"${var_name}: {gql_type}")
            variables[var_name] = value
            arg_strings.append(f"{name}: ${var_name}")

    return var_decls, arg_strings, variables, missing_required


def build_mutation_vars(args: list, record: dict, index: int) -> tuple:
    """Variable builder for mutation operations (create, update, delete, duplicate)."""
    return _build_operation_variables(args, record, index)


def build_query_vars(args: list, record: dict, index: int) -> tuple:
    """Variable builder for query operations (get/list)."""
    return _build_operation_variables(args, record, index)


def build_selection(return_type: dict, type_map: dict) -> str:
    """
    Builds the GraphQL selection set string for a mutation's return type.

    duplicate_* mutations return wrapper types (e.g. BoardDuplication) instead
    of plain entities (Board, Item). These wrappers don't have id/name at the
    top level, so we can't hardcode "{ id name }" like create/update do.
    Instead, we resolve the return type's fields from type_map — built from the
    single __schema call at the start of /schema — with no further API calls.

    Examples:
      BoardDuplication  ->  "{ board { id name } }"
      Board             ->  "{ id name ... }"   (scalar fields listed)
      JSON (scalar)     ->  ""                  (scalars need no selection set)
    """
    # Peel off NON_NULL wrapper to get to the actual type underneath.
    unwrapped_return_type = return_type
    if unwrapped_return_type.get("kind") == "NON_NULL":
        unwrapped_return_type = unwrapped_return_type.get("ofType") or unwrapped_return_type

    kind = unwrapped_return_type.get("kind")

    # Scalars and enums have no sub-fields to select.
    if kind in ("SCALAR", "ENUM"):
        return ""

    # For list return types, unwrap to the element type.
    if kind == "LIST":
        inner = unwrapped_return_type.get("ofType") or {}
        if inner.get("kind") == "NON_NULL":
            inner = inner.get("ofType") or inner
        if inner.get("kind") in ("SCALAR", "ENUM"):
            return ""
        unwrapped_return_type = inner

    type_name = unwrapped_return_type.get("name")
    if not type_name:
        return "{ id name }"

    fields = (type_map.get(type_name) or {}).get("fields") or []

    parts = []
    for field_definition in fields:
        field_type = field_definition["type"]
        if field_type.get("kind") == "NON_NULL":
            field_type = field_type.get("ofType") or field_type
        field_kind = field_type.get("kind")

        if field_kind in ("SCALAR", "ENUM"):
            # Plain value — select directly, e.g. "id", "name"
            parts.append(field_definition["name"])
        elif field_kind == "OBJECT":
            # Sub-object — select its id and name.
            # All Monday.com entity types (Board, Item, Group…) have id + name.
            parts.append(f"{field_definition['name']} {{ id name }}")

    return ("{ " + " ".join(parts) + " }") if parts else "{ id name }"
