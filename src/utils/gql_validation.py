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
