import logging

from src.utils.helper import get_credentials
from src.utils.monday_graphql_connector import run_monday_query
from workflows_cdk import ManagedError, Request, Response

logger = logging.getLogger("monday.content_builder")


def build_content_data(flask_request, filter_object_types, gql_root_type="Mutation"):
    """
    Shared /content handler. Introspects the given GraphQL root type, then delegates
    field filtering and label-building to the module-supplied filter_object_types callable.

    Args:
        flask_request: The Flask request object passed from the route.
        filter_object_types: Callable[[list[dict]], list[dict]] — receives the raw
            introspected field list and returns [{value, label}] pairs for the dropdown.
        gql_root_type: GraphQL root type to introspect, either "Mutation" or "Query".
    """
    try:
        request = Request(flask_request)
        data = request.data

        content_object_names = data.get("content_object_names", [])

        # content_object_names may arrive as a list of id-objects; flatten to plain strings
        if (
            isinstance(content_object_names, list)
            and content_object_names
            and isinstance(content_object_names[0], dict)
        ):
            content_object_names = [
                obj.get("id") for obj in content_object_names if "id" in obj
            ]

        try:
            credentials = get_credentials(flask_request)
        except ManagedError as e:
            logger.warning(
                "No credentials available for content request: %s",
                e,
                exc_info=True,
            )
            return Response(
                data={
                    "content_objects": [
                        {"content_object_name": name, "data": []}
                        for name in content_object_names
                    ]
                }
            )

        api_key = credentials.get("access_token")

        result = run_monday_query(
            query=f'{{ __type(name: "{gql_root_type}") {{ fields {{ name }} }} }}',
            token=api_key,
        )

        content_objects = []
        for content_object_name in content_object_names:
            if content_object_name == "object_types":
                fields = result["data"]["__type"]["fields"]
                content_objects.append(
                    {
                        "content_object_name": "object_types",
                        "data": filter_object_types(fields),
                    }
                )

        return Response(data={"content_objects": content_objects})

    except ManagedError:
        raise
    except Exception as e:
        logger.exception("Unexpected content request error")
        status_code = getattr(e, "status_code", 500)
        raise ManagedError(
            error="Failed to load content", status_code=status_code
        ) from e
