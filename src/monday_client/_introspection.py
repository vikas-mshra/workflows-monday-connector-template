from ._http import run_monday_query

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


def get_mutation_args(object_type: str, token: str) -> dict:
    """
    Returns args and return_type for a named mutation by introspecting
    Monday.com's Mutation type.

    Return value:
      {
        "args":        list of GraphQL arg definitions (name, description, type),
        "return_type": raw introspection type node for what the mutation returns
      }

    - args       → used by build_mutation_vars to validate inputs and build GQL variables
    - return_type → used by _build_selection to decide whether a selection set is needed
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
