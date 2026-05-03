from workflows_cdk import Response, Request, ManagedError
from flask import request as flask_request
import requests
from main import router

from model import run_monday_query
from utility import build_schema_from_args, humanize

MONDAY_API_URL = "https://api.monday.com/v2"


@router.route("/execute", methods=["GET", "POST"])
def execute():
    """
    This is the function that is executed when you click on "Run" on a workflow that uses this action.
    """
    try:
        request = Request(flask_request)
        data = request.data

        if not data:
            raise ManagedError("Missing request parameters")
        if not data.get("api_key"):
            raise ManagedError("Missing API key parameter")
        if not data.get("object_type"):
            raise ManagedError("Missing object type parameter")

        api_token = data.get("api_key")
        object_type = data.get("object_type")

        headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
        }

        results = []

        if object_type == "create_board":
            board_records = data.get("board_records")
            if not board_records:
                raise ManagedError("Missing board_records parameter")

            valid = []
            for record in board_records:
                if not record.get("board_name"):
                    results.append(
                        {
                            "success": False,
                            "error": "board_name is required",
                            "record": record,
                        }
                    )
                elif not record.get("board_kind"):
                    results.append(
                        {
                            "success": False,
                            "error": "board_kind is required",
                            "record": record,
                        }
                    )
                else:
                    valid.append(record)

            if valid:
                var_decls = []
                alias_blocks = []
                variables = {}

                for i, record in enumerate(valid):
                    s = str(i)

                    var_decls += [
                        f"$board_name_{s}: String!",
                        f"$board_kind_{s}: BoardKind!",
                    ]
                    variables[f"board_name_{s}"] = record["board_name"]
                    variables[f"board_kind_{s}"] = record["board_kind"]
                    args = [
                        f"board_name: $board_name_{s}",
                        f"board_kind: $board_kind_{s}",
                    ]

                    for field, gql_type in [
                        ("folder_id", "ID"),
                        ("workspace_id", "ID"),
                        ("template_id", "Int"),
                        ("description", "String"),
                        ("empty", "Boolean"),
                    ]:
                        if record.get(field) is not None:
                            var_decls.append(f"${field}_{s}: {gql_type}")
                            variables[f"{field}_{s}"] = record[field]
                            args.append(f"{field}: ${field}_{s}")

                    if record.get("item_nickname"):
                        var_decls.append(f"$item_nickname_{s}: ItemNicknameInput")
                        variables[f"item_nickname_{s}"] = record["item_nickname"]
                        args.append(f"item_nickname: $item_nickname_{s}")

                    for field, item_key in [
                        ("board_owner_ids", "board_owner_id"),
                        ("board_owner_team_ids", "board_owner_team_id"),
                        ("board_subscriber_ids", "board_subscriber_id"),
                        ("board_subscriber_teams_ids", "board_subscriber_teams_id"),
                    ]:
                        ids = [
                            str(item[item_key])
                            for item in (record.get(field) or [])
                            if item.get(item_key)
                        ]
                        if ids:
                            var_decls.append(f"${field}_{s}: [ID!]")
                            variables[f"{field}_{s}"] = ids
                            args.append(f"{field}: ${field}_{s}")

                    alias_blocks.append(
                        f"board_{i}: create_board({', '.join(args)}) {{ id name state }}"
                    )

                mutation = (
                    f"mutation ({', '.join(var_decls)}) {{ {' '.join(alias_blocks)} }}"
                )

                response = requests.post(
                    MONDAY_API_URL,
                    json={"query": mutation, "variables": variables},
                    headers=headers,
                )
                response.raise_for_status()
                api_result = response.json()

                if "errors" in api_result:
                    for record in valid:
                        results.append(
                            {
                                "success": False,
                                "error": api_result["errors"],
                                "record": record,
                            }
                        )
                else:
                    for i, record in enumerate(valid):
                        created = api_result["data"].get(f"board_{i}")
                        if created:
                            results.append(
                                {
                                    "success": True,
                                    "id": created["id"],
                                    "name": created["name"],
                                    "state": created["state"],
                                }
                            )
                        else:
                            results.append(
                                {
                                    "success": False,
                                    "error": "No data returned",
                                    "record": record,
                                }
                            )

        else:
            raise ManagedError(f"Unsupported object type: {object_type}")

        successful = sum(1 for r in results if r["success"])
        return Response(
            data={"results": results},
            metadata={"affected_rows": successful},
        )
    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))


@router.route("/content", methods=["GET", "POST"])
def content():
    try:
        request = Request(flask_request)

        data = request.data

        form_data = data.get("form_data", {})
        content_object_names = data.get("content_object_names", [])

        # Extract content object names from objects if needed
        if (
            isinstance(content_object_names, list)
            and content_object_names
            and isinstance(content_object_names[0], dict)
        ):
            content_object_names = [
                obj.get("id") for obj in content_object_names if "id" in obj
            ]

        content_objects = []  # this is the list of content objects that will be returned to the frontend

        api_token = form_data.get("api_key")
        # object_type = form_data.get("object_type")

        if not api_token:
            raise ManagedError("Missing API key parameter")

        # Build the headers
        headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
        }

        query = """
            {
                boards(limit: 10) {
                    id
                    name
                    state
                    workspace_id
                }

                workspaces(limit: 10) {
                    id
                    name
                    kind
                }

                users(limit: 10) {
                    id
                    name
                    email
                }

                teams {
                    id
                    name
                }

                tags {
                    id
                    name
                }

                docs(limit: 10) {
                    id
                    name
                }

                folders(limit: 10) {
                    id
                    name
                }

                account {
                    id
                    name
                }
            }
        """
        response = requests.post(MONDAY_API_URL, json={"query": query}, headers=headers)
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            raise ManagedError(f"Monday.com API error: {result['errors']}")

        for content_object_name in content_object_names:
            if content_object_name == "object_types":
                top_modules = result["data"].keys()
                data = [{"value": module, "label": module} for module in top_modules]

                content_objects.append(
                    {"content_object_name": "object_types", "data": data}
                )

        return Response(data={"content_objects": content_objects})

    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))


BASE_METADATA = {"workflows_module_schema_version": "1.0.0"}
BASE_FIELDS = [
    {
        "id": "api_key",
        "type": "string",
        "label": "API Key",
        "description": "Your API key for authentication with Monday.com",
        "validation": {"required": True},
    },
    {
        "id": "object_type",
        "type": "string",
        "label": "Object Type",
        "description": "Select the object type to reveal its specific fields",
        "validation": {"required": True},
        "on_action": {"load_schema": True},
        "choices": [
            {"value": "create_board", "label": "Board"},
            {"value": "create_item", "label": "Item"},
            {"value": "create_subitem", "label": "Subitem"},
            {"value": "create_update", "label": "Update"},
            {"value": "create_workspace", "label": "Workspace"},
            {"value": "create_folder", "label": "Folder"},
            {"value": "create_group", "label": "Group"},
        ],
        "ui_options": {"ui_widget": "SelectWidget"},
    },
]
BASE_UI_OPTIONS = {"ui_order": ["api_key", "object_type"]}


@router.route("/schema", methods=["GET", "POST"])
def schema():
    try:
        request = Request(flask_request)
        data = request.data

        form_data = data.get("form_data", {})
        object_type = form_data.get("object_type")
        api_key = form_data.get("api_key")

        response = Response(
            data={
                "schema": {
                    "metadata": BASE_METADATA,
                    "fields": BASE_FIELDS,
                    "ui_options": BASE_UI_OPTIONS,
                }
            }
        )

        if not api_key:
            return response

        # fetch the schema for the object type
        query = """
            query {
                __type(name: "Mutation") {
                    fields {
                    name
                    args {
                        name
                        type {
                        name
                        kind
                        ofType {
                            name
                            kind
                        }
                        }
                        description
                    }
                    }
                }
            }
        """
        # 1. Run the query to get the mutation fields
        result = run_monday_query(query=query, token=api_key)

        # 2. Extract mutation fields
        fields = result["data"]["__type"]["fields"]

        # 3. Find create_board
        create_fields_args = []
        for field in fields:
            if field["name"] == object_type:
                create_fields_args = field["args"]
                break

        fields, ui_order = build_schema_from_args(create_fields_args, api_key)

        schema = [
            {
                "id": object_type,
                "type": "array",
                "label": f"{humanize(object_type)} Records",
                "description": f"List of {humanize(object_type)} to create",
                "default": [{}],
                "items": {
                    "type": "object",
                    "default": {},
                    "fields": fields,
                    "ui_options": {"ui_order": ui_order},
                },
            }
        ]
        return Response(
            data={
                "schema": {
                    "metadata": BASE_METADATA,
                    "fields": [
                        *BASE_FIELDS,
                        *schema,
                    ],
                    "ui_options": {"ui_order": ["api_key", "object_type", "records"]},
                }
            }
        )

        return response
    except ManagedError as e:
        return Response.error(str(e))
    except Exception as e:
        return Response.error(str(e))
