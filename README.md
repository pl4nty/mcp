# mcp-servers

A monorepo of remote MCP servers built with the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) and Docker, designed to work with [Claude custom connectors](https://support.claude.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers).

## Servers

| Server | Description |
|--------|-------------|
| [outlook](./servers/outlook) | Search and read Outlook emails and calendar events via Microsoft Graph API |

## Architecture

Each server is a standalone Python package using [FastMCP](https://github.com/modelcontextprotocol/python-sdk) with Streamable HTTP transport. Authentication follows the OAuth 2.1 pattern required by Claude's custom connectors — each server acts as an OAuth Authorization Server with a pre-configured static client (no dynamic registration), and uses [DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.aio.defaultazurecredential) to access Microsoft APIs.

## Running locally

```bash
cd servers/outlook
docker build -t outlook-mcp .
docker run -p 8000:8000 -e MCP_CLIENT_ID=... -e MCP_CLIENT_SECRET=... \
  -e AZURE_TENANT_ID=... -e AZURE_CLIENT_ID=... -e AZURE_CLIENT_SECRET=... \
  -e GRAPH_USER=user@example.com outlook-mcp
```

The servers will be available at:
- Outlook MCP: `http://localhost:8000/mcp`

## Adding a connector to Claude

1. Go to **Claude** → **Settings** → **Connectors** → **Add custom connector**
2. Enter the server URL (e.g. `http://localhost:8000/mcp` for local development or your deployed URL)
3. Claude will guide you through the OAuth flow to authenticate with Microsoft

See each server's README for detailed setup instructions.