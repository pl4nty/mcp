"""Schema validation tools — validate XML/JSON against bundled or URL-sourced schemas."""

import json
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse, unquote

import httpx
import jsonschema
from lxml import etree

from tools.runtime import mcp

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Schema registry: id → {description, url | path}
# 'url'  — fetch schema content from this URL at runtime
# 'path' — read schema content from this local file
_SCHEMAS: dict[str, dict] = {
    "admx": {
        "description": "ADMX/ADML Group Policy policy definition files schema",
        "url": "https://raw.githubusercontent.com/pl4nty/admxgen/refs/heads/master/admxgen/PolicyDefinitionFiles.xsd",
    },
    "assigned-access": {
        "description": "Windows Assigned Access configuration schema",
        "url": "https://raw.githubusercontent.com/MostlyCompliantEndpoint/Mostly-Compliant-Endpoint/refs/heads/main/Assigned%20Access%20Designer/Source/AssignedAccessDesigner/Assets/AssignedAccess.xsd",
    },
    "chromium-extensions": {
        "description": "Chromium browser ExtensionSettings policy JSON schema (derived from https://source.chromium.org/chromium/chromium/src/+/main:out/win-Debug/gen/components/policy/proto/chrome_settings.proto)",
        "path": _DATA_DIR / "chromium_extensions.json",
    },
}

# Runtime content caches
_content_cache: dict[str, str] = {}
_xsd_cache: dict[str, etree.XMLSchema] = {}
_json_schema_cache: dict[str, dict] = {}

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient()
    return _http_client


def _schema_type(schema_id: str) -> str:
    """Determine schema type from the file extension of the url or path."""
    info = _SCHEMAS[schema_id]
    if "url" in info:
        suffix = PurePosixPath(unquote(urlparse(info["url"]).path)).suffix.lower()
    else:
        suffix = info["path"].suffix.lower()
    return "xsd" if suffix == ".xsd" else "json"


async def _fetch_content(schema_id: str) -> str:
    """Return raw schema text, fetching from URL or reading from disk."""
    if schema_id not in _content_cache:
        info = _SCHEMAS[schema_id]
        if "url" in info:
            try:
                resp = await _get_http_client().get(info["url"])
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Failed to fetch schema '{schema_id}' from {info['url']}: HTTP {exc.response.status_code}"
                ) from exc
            _content_cache[schema_id] = resp.text
        else:
            _content_cache[schema_id] = info["path"].read_text(encoding="utf-8")
    return _content_cache[schema_id]


async def _get_xsd(schema_id: str) -> etree.XMLSchema:
    if schema_id not in _xsd_cache:
        text = await _fetch_content(schema_id)
        doc = etree.fromstring(text.encode("utf-8"))
        _xsd_cache[schema_id] = etree.XMLSchema(doc)
    return _xsd_cache[schema_id]


async def _get_json_schema(schema_id: str) -> dict:
    if schema_id not in _json_schema_cache:
        text = await _fetch_content(schema_id)
        _json_schema_cache[schema_id] = json.loads(text)
    return _json_schema_cache[schema_id]


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

    errors: list[str] = []

    if _schema_type(schema_id) == "xsd":
        try:
            xsd = await _get_xsd(schema_id)
            doc = etree.fromstring(content.encode("utf-8"))
            if not xsd.validate(doc):
                errors = [str(e) for e in xsd.error_log]
        except etree.XMLSyntaxError as exc:
            errors = [f"XML parse error: {exc}"]
    else:
        try:
            instance = json.loads(content)
            schema = await _get_json_schema(schema_id)
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
        {"id": sid, "type": _schema_type(sid), "description": info["description"]}
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
    return await _fetch_content(schema_id)
