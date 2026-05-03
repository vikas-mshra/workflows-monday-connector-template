MONDAY_API_URL = "https://api.monday.com/v2"

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
        "choices": {"values": []},
        "content": {
            "type": ["managed"],
            "content_objects": [{"id": "object_types"}],
        },
        "ui_options": {"ui_widget": "SelectWidget"},
    },
]

BASE_UI_OPTIONS = {"ui_order": ["api_key", "object_type"]}
