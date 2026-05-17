import time

from ._http import run_monday_query

# Keyed by token so different users don't share cached data.
# Each entry is (type_map, fetched_at) — TTL prevents serving a stale schema
# after Monday.com releases new mutations or deprecates existing ones.
_type_map_cache: dict = {}
_CACHE_TTL_SECONDS = 300

# Both functions use the same introspection shape — 4 levels of ofType nesting
# covers the deepest type wrapping Monday.com uses (e.g. NON_NULL(LIST(NON_NULL(SCALAR)))).
_ARG_TYPE_FRAGMENT = """
    name
    kind
    ofType {
        name
        kind
        ofType {
            name
            kind
            ofType {
                name
                kind
            }
        }
    }
"""

# __schema query fetches every type in the Monday.com schema in one round-trip.
# Used by get_schema_type_map to build a {name: type_def} dict so /schema can
# resolve all enum values, input fields, and return type fields without further
# API calls. TypeRef fragment nests ofType 4 levels deep — enough for Monday's
# deepest real wrapping: NON_NULL(LIST(NON_NULL(INPUT_OBJECT))).
_SCHEMA_QUERY = """
    query {
        __schema {
            types {
                name
                kind
                enumValues(includeDeprecated: true) { name }
                inputFields {
                    name description defaultValue
                    type {
                        ...TypeRef
                    }
                }
                fields(includeDeprecated: true) {
                    name description
                    type { ...TypeRef }
                    args {
                        name description defaultValue
                        type { ...TypeRef }
                    }
                }
            }
        }
    }
    fragment TypeRef on __Type {
        kind name
        ofType { kind name
            ofType { kind name
                ofType { kind name
                    ofType { kind name } } } }
    }
"""


def get_schema_type_map(token: str) -> dict:
    """
    Returns a {type_name: type_definition} map for the full Monday.com schema.

    Results are cached per token for _CACHE_TTL_SECONDS (default 5 min) so
    repeated calls within a request session — e.g. /schema followed by /execute
    in duplicate or add_data — cost zero extra API calls. Each worker process
    maintains its own cache; the TTL ensures schema changes are picked up without
    a server restart.
    """
    cached = _type_map_cache.get(token)
    if cached:
        type_map, fetched_at = cached
        if time.time() - fetched_at < _CACHE_TTL_SECONDS:
            return type_map

    result = run_monday_query(query=_SCHEMA_QUERY, token=token)
    type_map = {t["name"]: t for t in result["data"]["__schema"]["types"] if t["name"]}
    _type_map_cache[token] = (type_map, time.time())
    return type_map


def get_mutation_args_from_map(object_type: str, type_map: dict) -> dict:
    """
    Returns args and return_type for a named mutation by looking up the
    pre-fetched type_map instead of calling the API.

    Same return shape as get_mutation_args.
    """
    for field in (type_map.get("Mutation") or {}).get("fields") or []:
        if field["name"] == object_type:
            return {"args": field["args"], "return_type": field["type"]}
    return {"args": [], "return_type": {"kind": "SCALAR", "name": None}}


def get_query_args_from_map(object_type: str, type_map: dict) -> dict:
    """
    Returns args and return_type for a named query field by looking up the
    pre-fetched type_map instead of calling the API.

    Same return shape as get_query_args.
    """
    for field in (type_map.get("Query") or {}).get("fields") or []:
        if field["name"] == object_type:
            return {"args": field["args"], "return_type": field["type"]}
    return {"args": [], "return_type": {"kind": "SCALAR", "name": None}}


def get_mutation_args(object_type: str, token: str) -> dict:
    """
    Returns args and return_type for a named mutation by introspecting
    Monday.com's Mutation type.

    Return value:
      {
        "args":        list of GraphQL arg definitions (name, description, type),
        "return_type": raw introspection type node for what the mutation returns
      }

    - args       → used by build_request_variables to validate inputs and build GQL variables
    - return_type → used by build_response_selection to decide whether a selection set is needed
    """
    query = f"""
        query {{
            __type(name: "Mutation") {{
                fields {{
                    name
                    type {{ {_ARG_TYPE_FRAGMENT} }}
                    args {{
                        name
                        description
                        defaultValue
                        type {{ {_ARG_TYPE_FRAGMENT} }}
                    }}
                }}
            }}
        }}
    """
    result = run_monday_query(query=query, token=token)
    for field in result["data"]["__type"]["fields"]:
        if field["name"] == object_type:
            return {"args": field["args"], "return_type": field["type"]}
    return {"args": [], "return_type": {"kind": "SCALAR", "name": None}}


def get_query_args(object_type: str, token: str) -> dict:
    """
    Returns args and return_type for a named query field by introspecting
    Monday.com's Query type.

    Same shape as get_mutation_args — only the root type differs (Query vs Mutation).
    """
    query = f"""
        query {{
            __type(name: "Query") {{
                fields {{
                    name
                    type {{ {_ARG_TYPE_FRAGMENT} }}
                    args {{
                        name
                        description
                        defaultValue
                        type {{ {_ARG_TYPE_FRAGMENT} }}
                    }}
                }}
            }}
        }}
    """
    result = run_monday_query(query=query, token=token)
    for field in result["data"]["__type"]["fields"]:
        if field["name"] == object_type:
            return {"args": field["args"], "return_type": field["type"]}
    return {"args": [], "return_type": {"kind": "SCALAR", "name": None}}
