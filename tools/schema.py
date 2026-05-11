"""Schema validation tools — validate XML/JSON against bundled schemas."""

import json
from pathlib import Path

import jsonschema
from lxml import etree

from tools.runtime import mcp

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Schema registry: id → {type, description, path, source}
_SCHEMAS: dict[str, dict] = {
    "admx": {
        "type": "xsd",
        "description": "ADMX/ADML Group Policy policy definition files schema",
        "path": _DATA_DIR / "PolicyDefinitionFiles.xsd",
        "source": "https://raw.githubusercontent.com/pl4nty/admxgen/refs/heads/master/admxgen/PolicyDefinitionFiles.xsd",
    },
    "assigned-access": {
        "type": "xsd",
        "description": "Windows Assigned Access configuration schema",
        "path": _DATA_DIR / "AssignedAccess.xsd",
        "source": "https://raw.githubusercontent.com/MostlyCompliantEndpoint/Mostly-Compliant-Endpoint/refs/heads/main/Assigned%20Access%20Designer/Source/AssignedAccessDesigner/Assets/AssignedAccess.xsd",
    },
    "chromium-extensions": {
        "type": "json",
        "description": "Chromium browser ExtensionSettings policy JSON schema (derived from https://source.chromium.org/chromium/chromium/src/+/main:out/win-Debug/gen/components/policy/proto/chrome_settings.proto)",
        "path": _DATA_DIR / "chromium_extensions.json",
        "source": "https://source.chromium.org/chromium/chromium/src/+/main:out/win-Debug/gen/components/policy/proto/chrome_settings.proto",
    },
}

# Caches
_xsd_cache: dict[str, etree.XMLSchema] = {}
_json_cache: dict[str, dict] = {}


def _get_xsd(schema_id: str) -> etree.XMLSchema:
    if schema_id not in _xsd_cache:
        path = _SCHEMAS[schema_id]["path"]
        doc = etree.parse(str(path))
        _xsd_cache[schema_id] = etree.XMLSchema(doc)
    return _xsd_cache[schema_id]


def _get_json_schema(schema_id: str) -> dict:
    if schema_id not in _json_cache:
        path = _SCHEMAS[schema_id]["path"]
        _json_cache[schema_id] = json.loads(path.read_text(encoding="utf-8"))
    return _json_cache[schema_id]


@mcp.tool()
async def validate(content: str, schema_id: str) -> dict:
    """Validate content against a schema.

    Args:
        content: The XML or JSON content to validate.
        schema_id: The schema identifier (use list_schemas to see available IDs).

    Returns:
        A ValidationResult with 'valid' (bool) and 'errors' (list of strings).
    """
    if schema_id not in _SCHEMAS:
        return {"valid": False, "errors": [f"Unknown schema id: {schema_id}. Use list_schemas() to see available schemas."]}

    schema_info = _SCHEMAS[schema_id]
    errors: list[str] = []

    if schema_info["type"] == "xsd":
        try:
            xsd = _get_xsd(schema_id)
            doc = etree.fromstring(content.encode("utf-8"))
            if not xsd.validate(doc):
                errors = [str(e) for e in xsd.error_log]
        except etree.XMLSyntaxError as exc:
            errors = [f"XML parse error: {exc}"]
    elif schema_info["type"] == "json":
        try:
            instance = json.loads(content)
            schema = _get_json_schema(schema_id)
            validator = jsonschema.Draft7Validator(schema)
            errors = [e.message for e in validator.iter_errors(instance)]
        except json.JSONDecodeError as exc:
            errors = [f"JSON parse error: {exc}"]

    return {"valid": len(errors) == 0, "errors": errors}


@mcp.tool()
async def list_schemas() -> list[dict]:
    """List all available validation schemas.

    Returns:
        A list of schema descriptors with 'id', 'type', and 'description'.
    """
    return [
        {"id": sid, "type": info["type"], "description": info["description"]}
        for sid, info in _SCHEMAS.items()
    ]


@mcp.tool()
async def get_schema(schema_id: str) -> str:
    """Get the raw schema content by its identifier.

    Args:
        schema_id: The schema identifier (use list_schemas to see available IDs).

    Returns:
        The raw schema text (XSD XML or JSON).
    """
    if schema_id not in _SCHEMAS:
        return f"Unknown schema id: {schema_id}. Use list_schemas() to see available schemas."
    return _SCHEMAS[schema_id]["path"].read_text(encoding="utf-8")
