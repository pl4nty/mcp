# Outlook MCP Server

A remote MCP server that provides tools for searching and reading Outlook emails and calendar events via the [Microsoft Graph Beta API](https://github.com/microsoftgraph/msgraph-beta-sdk-python).

## Authentication

Two independent credential pairs are needed:

### 1. Claude → MCP server (OAuth 2.1)

Configure a static client ID and secret that Claude uses to authenticate:

```env
MCP_CLIENT_ID=your-mcp-client-id
MCP_CLIENT_SECRET=your-mcp-client-secret
```

Choose any opaque values (e.g. generate a UUID for the ID and a long random string for the secret). Enter these same values when adding the connector in Claude.

### 2. MCP server → Microsoft Graph (DefaultAzureCredential)

Register an application in [Microsoft Entra ID](https://portal.azure.com) with **application** (not delegated) permissions:

1. **App registrations** → **New registration**
2. Note the **Application (client) ID** and **Directory (tenant) ID**
3. **Certificates & secrets** → **New client secret** → copy the secret value
4. **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions**:
   - `Mail.Read`
   - `Calendars.Read`
5. Click **Grant admin consent**

Set the following environment variables:

```env
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-app-client-id
AZURE_CLIENT_SECRET=your-app-client-secret
GRAPH_USER=user@example.com   # UPN or object ID of the mailbox/calendar to access
```

`DefaultAzureCredential` also supports Managed Identity, workload identity, and other Azure auth mechanisms — see the [azure-identity docs](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity?view=azure-python).

## Running

```bash
cd servers/outlook
docker build -t outlook-mcp .
docker run -p 8000:8000 \
  -e MCP_CLIENT_ID=... \
  -e MCP_CLIENT_SECRET=... \
  -e AZURE_TENANT_ID=... \
  -e AZURE_CLIENT_ID=... \
  -e AZURE_CLIENT_SECRET=... \
  -e GRAPH_USER=user@example.com \
  -e SERVER_URL=http://localhost:8000 \
  outlook-mcp
```

Or directly with uv:

```bash
uv run python -m outlook_mcp.server
```

## Adding to Claude

1. Start the server (see above)
2. In Claude → **Settings** → **Connectors** → **Add custom connector**
3. Enter `http://localhost:8000/mcp` (or your deployed URL)
4. When prompted, enter the `MCP_CLIENT_ID` and `MCP_CLIENT_SECRET` values you configured

## Available tools

| Tool | Description |
|------|-------------|
| `search_emails` | Search emails using a free-text query |
| `list_emails` | List emails from a folder with optional filters (unread, date range) |
| `read_email` | Read the full content of a specific email by ID |
| `list_calendar_events` | List calendar events with optional date range filter |
| `search_calendar_events` | Search calendar events by subject or body text |
