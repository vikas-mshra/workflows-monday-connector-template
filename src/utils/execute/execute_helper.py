import json
import re

from workflows_cdk import ManagedError

from src.utils.utils import extract_inner_type, unwrap_non_null_fully


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


def build_payload_for_monday(args: list, record: dict, index: int) -> tuple:
    """
    Builds the GraphQL **request** side for one record in a batched operation:
    variable declarations, inline arg strings, the variables dict to send, and
    a list of any missing required field names.

    Works for both mutations and queries — callers use the same function
    regardless of operation type. Collecting missing-required names in the
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
        actual_kind, actual_name, required = extract_inner_type(arg["type"])
        var_name = f"{name}_{index_suffix}"
        gql_type = _gql_type_string(arg["type"])

        if actual_kind == "LIST":
            # Peel NON_NULL → LIST → inner NON_NULL to find the element kind. The
            # schema builder renders each LIST shape differently, so we have to
            # mirror that here to pull the values back out the right way.
            list_type, _ = unwrap_non_null_fully(arg["type"])
            element_type, _ = unwrap_non_null_fully(list_type.get("ofType") or {})
            element_kind = element_type.get("kind")
            element_name = element_type.get("name")

            raw_items = record.get(name) or []

            if element_kind == "INPUT_OBJECT":
                # _build_object_field renders LIST(INPUT_OBJECT) items with the
                # INPUT_OBJECT's real sub-field names, so each form item is already
                # shaped like the GraphQL input — pass dicts through. Empty items
                # are dropped for the same reason as the top-level INPUT_OBJECT
                # branch (Monday rejects {} as VALIDATION_INVALID_TYPE_VARIABLE).
                items = [
                    item
                    for item in raw_items
                    if isinstance(item, dict) and not _is_empty_input(item)
                ]
            else:
                # LIST(SCALAR) and LIST(ENUM) items are single-key dicts whose key
                # is the arg name itself — see _build_array_field's default item
                # builder and the LIST(ENUM) branch in build_schema_from_args.
                # The two sides are coupled: change them together.
                items = [
                    item[name]
                    for item in raw_items
                    if isinstance(item, dict) and not _is_empty_input(item.get(name))
                ]
                # Monday IDs routinely exceed 2^53; coerce numeric inputs so they
                # don't lose precision on the JSON round-trip. Only for ID — Int
                # and Float must stay numeric to pass Monday's type validation.
                if element_kind == "SCALAR" and element_name == "ID":
                    items = [str(v) for v in items]

            if not items:
                if required:
                    missing_required.append(name)
                continue
            var_decls.append(f"${var_name}: {gql_type}")
            variables[var_name] = items
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
            # Monday.com IDs are strings (and routinely exceed 2^53). Coerce so
            # numeric inputs from the form don't get round-tripped through a
            # JS double and lose precision.
            if actual_kind == "SCALAR" and actual_name == "ID":
                value = str(value)
            # Monday.com's JSON scalar expects a JSON string (not a parsed object).
            # If the value is a dict (e.g. sent as an object from the form), stringify it.
            # If it's already a string (from CodeblockWidget), strip trailing commas
            # so Monday.com's parser accepts it.
            if actual_kind == "SCALAR" and actual_name == "JSON":
                if isinstance(value, dict):
                    value = json.dumps(value)
                elif isinstance(value, str):
                    cleaned = re.sub(r",\s*([}\]])", r"\1", value)
                    try:
                        json.loads(cleaned)
                    except json.JSONDecodeError as e:
                        # e.msg + e.pos only — never include e.doc / the raw value,
                        # which may contain PII the user typed into column_values.
                        raise ManagedError(
                            f"Invalid JSON in field '{name}': {e.msg} at position {e.pos}"
                        )
                    value = cleaned
            var_decls.append(f"${var_name}: {gql_type}")
            variables[var_name] = value
            arg_strings.append(f"{name}: ${var_name}")

    return var_decls, arg_strings, variables, missing_required


def parameter_to_fetch_from_monday(return_type: dict, type_map: dict) -> str:
    """
    Builds the GraphQL **response** selection set for a mutation/query return type.

    Works for any return type by resolving its fields from type_map (built once
    per request from a single __schema call). For plain entities (Board, Item)
    this lists every scalar/enum field. For wrapper types like BoardDuplication
    — returned by duplicate_* mutations — it yields the wrapper's sub-object
    selection (e.g. "{ board { id } }"). Hardcoded selections would not handle
    both shapes, so we always introspect.

    Examples:
      BoardDuplication  ->  "{ board { id } }"
      Board             ->  "{ id name ... owner { id } groups { id } updates { id } ... }"
      JSON (scalar)     ->  ""                  (scalars need no selection set)

    Design notes (future scope):
      * Only goes ONE level deep into OBJECT / LIST(OBJECT) sub-fields, emitting
        `{ id }` for them. See the inline comment on the OBJECT branch for the
        rationale (no common human-readable field across Monday.com types).
        Callers needing more than the id for a sub-object should do a follow-up
        query using that id.
      * Sub-fields whose introspection declares required arguments (e.g.
        Board.items_page(limit: Int!)) are filtered out — selecting them bare
        would emit invalid GraphQL.
    """
    # Peel off NON_NULL wrapper to get to the actual type underneath.
    unwrapped_return_type, _ = unwrap_non_null_fully(return_type)

    kind = unwrapped_return_type.get("kind")

    # Scalars and enums have no sub-fields to select.
    if kind in ("SCALAR", "ENUM"):
        return ""

    # For list return types, unwrap to the element type.
    if kind == "LIST":
        inner, _ = unwrap_non_null_fully(unwrapped_return_type.get("ofType") or {})
        if inner.get("kind") in ("SCALAR", "ENUM"):
            return ""
        unwrapped_return_type = inner

    type_name = unwrapped_return_type.get("name")
    if not type_name:
        return "{ id }"

    fields = (type_map.get(type_name) or {}).get("fields") or []

    parts = []
    for field_definition in fields:
        # Skip fields that require arguments — selecting them bare emits invalid GraphQL
        # (e.g. Board.items_page(limit: Int!) would fail Monday.com's argument validation).
        field_args = field_definition.get("args") or []
        if any((arg.get("type") or {}).get("kind") == "NON_NULL" for arg in field_args):
            continue

        field_type, _ = unwrap_non_null_fully(field_definition["type"])
        field_kind = field_type.get("kind")

        if field_kind in ("SCALAR", "ENUM"):
            # Plain value — select directly, e.g. "id", "name"
            parts.append(field_definition["name"])
        elif field_kind == "OBJECT":
            # Only emit `id` for sub-objects. Monday.com entity types don't share
            # a common human-readable field — Board/User use `name`, Group/View
            # use `title`, Update uses `body`, ActivityLogType uses `event`, etc.
            # — so any hardcoded label would break on at least one type. Pulling
            # every scalar on every sub-object would generalize but bloats the
            # response and risks Monday's complexity limits. `id` is universal and
            # sufficient — callers who need details can fetch the sub-object with
            # a follow-up request using the id.
            parts.append(f"{field_definition['name']} {{ id }}")
        elif field_kind == "LIST":
            # Peel LIST and an optional inner NON_NULL to find the element kind.
            element_type, _ = unwrap_non_null_fully(field_type.get("ofType") or {})
            element_kind = element_type.get("kind")
            if element_kind in ("SCALAR", "ENUM"):
                parts.append(field_definition["name"])
            elif element_kind == "OBJECT":
                # Same rationale as the OBJECT branch — `id` only.
                parts.append(f"{field_definition['name']} {{ id }}")
            # Lists of INTERFACE / UNION are skipped — not used on Monday.com entity types.

    return ("{ " + " ".join(parts) + " }") if parts else "{ id }"
