# mcp-servers

A monorepo of remote MCP servers built with the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) and Docker, designed to work with [Claude custom connectors](https://support.claude.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers).

## Servers

| Server | Description |
|--------|-------------|
| [outlook](./servers/outlook) | Search and read Outlook emails and calendar events via Microsoft Graph API |

## Architecture

Each server is a standalone Python package using [FastMCP](https://github.com/modelcontextprotocol/python-sdk) with Streamable HTTP transport. Authentication follows the OAuth 2.1 pattern required by Claude's custom connectors — each server acts as an OAuth Authorization Server that proxies user authentication to Microsoft Entra ID (formerly Azure AD), then issues its own tokens to the MCP client.

## Running locally

```bash
docker compose up
```

The servers will be available at:
- Outlook MCP: `http://localhost:8000/mcp`

## Adding a connector to Claude

1. Go to **Claude** → **Settings** → **Connectors** → **Add custom connector**
2. Enter the server URL (e.g. `http://localhost:8000/mcp` for local development or your deployed URL)
3. Claude will guide you through the OAuth flow to authenticate with Microsoft

See each server's README for detailed setup instructions.