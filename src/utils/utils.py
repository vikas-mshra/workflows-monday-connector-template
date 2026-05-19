import re

from workflows_cdk import ManagedError

# GraphQL Name spec: /^[_A-Za-z][_0-9A-Za-z]*$/. Validated explicitly wherever
# object_type flows from request data into a raw GraphQL string or a JSON id.
# Downstream introspection lookups also exact-match, but that's an implicit
# defense — a future refactor to a substring/prefix match would silently
# remove the boundary unless this check stays in place.
_GQL_NAME_RE = re.compile(r"^[_A-Za-z][_0-9A-Za-z]*$")


def validate_object_type(object_type: str) -> None:
    if not _GQL_NAME_RE.match(object_type or ""):
        raise ManagedError(f"Invalid object type: {object_type}")


def humanize(name: str) -> str:
    """Converts a snake_case identifier to a Title Case human label."""
    return name.replace("_", " ").title()


def extract_inner_type(type_info: dict) -> tuple:
    """
    Unwraps one level of NON_NULL and returns (kind, name, required).

    GraphQL marks required args as NON_NULL(actualType). We peel that wrapper
    so callers can work with the real kind/name while still knowing it's required.
    """
    if type_info["kind"] == "NON_NULL":
        of_type = type_info.get("ofType") or {}
        return of_type.get("kind"), of_type.get("name"), True
    return type_info["kind"], type_info.get("name"), False


def unwrap_non_null_fully(type_info: dict) -> tuple:
    """
    Fully unwraps all NON_NULL wrappers, returning (inner_type_dict, required).

    Unlike extract_inner_type (which peels exactly one layer and returns only kind/name),
    this returns the actual type dict so callers can continue walking ofType — necessary
    for stacked wrappers like NON_NULL(LIST(NON_NULL(INPUT_OBJECT))).
    """
    required = False
    current_type = type_info
    while current_type and current_type.get("kind") == "NON_NULL":
        required = True
        current_type = current_type.get("ofType") or {}
    return current_type, required
