from src.utils.monday_graphql_connector import run_monday_query


def get_type_definitions(token: str) -> dict:
    """
    Returns a {type_name: type_definition} map for the full Monday.com schema.
    """
    query = """
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
    result = run_monday_query(query=query, token=token)
    return {t["name"]: t for t in result["data"]["__schema"]["types"] if t["name"]}


def get_mutation_field_definitions(token: str) -> dict:
    """
    Returns a {"Mutation": type_definition} map for the mutation fields of Monday.com schema.
    Return value:
      {
        "Mutation": type_definition (fields)
      }

    - args → used by create/update/delete to build GQL variables
    """
    query = """
        query {
            __type(name: "Mutation") {
                fields {
                    name
                    type { ...ArgTypeRef }
                    args {
                        name
                        description
                        defaultValue
                        type { ...ArgTypeRef }
                    }
                }
            }
        }
        fragment ArgTypeRef on __Type {
            name kind
            ofType { name kind
                ofType { name kind
                    ofType { kind name
                        ofType { name kind } } } }
        }
    """
    result = run_monday_query(query=query, token=token)
    return {"Mutation": result["data"]["__type"]}
