# Outlook MCP Server

A remote MCP server that provides tools for searching and reading Outlook emails and calendar events via the [Microsoft Graph Beta API](https://github.com/microsoftgraph/msgraph-beta-sdk-python).

## Authentication

Authentication uses OAuth 2.1 with Microsoft Entra ID (formerly Azure AD), proxied through this server so Claude's custom connector OAuth flow works seamlessly. The server acts as an OAuth Authorization Server for Claude, redirecting users to Microsoft's login for the actual authentication.

### Set up an Entra ID app registration

1. Go to the [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations** → **New registration**
2. Name: anything descriptive (e.g. `Outlook MCP`)
3. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts** (for outlook.com support)
4. Redirect URI: **Web** → `https://your-server.example.com/oauth/callback` (or `http://localhost:8000/oauth/callback` for local dev)
5. Click **Register**
6. Note the **Application (client) ID** and **Directory (tenant) ID**
7. Go to **Certificates & secrets** → **New client secret** → copy the secret value
8. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:
   - `Mail.Read`
   - `Calendars.Read`
   - `User.Read`
   - `offline_access`
9. Click **Grant admin consent** (or let users consent individually)

### Configure environment variables

Create a `.env` file in the repository root (or set environment variables):

```env
ENTRA_TENANT_ID=your-tenant-id
ENTRA_CLIENT_ID=your-client-id
ENTRA_CLIENT_SECRET=your-client-secret
SERVER_URL=http://localhost:8000   # public-facing URL of this server
```

For **personal Microsoft accounts (outlook.com)**, use `common` as the tenant ID:

```env
ENTRA_TENANT_ID=common
```

## Running

### With Docker Compose (recommended)

From the repository root:

```bash
docker compose up outlook
```

### Directly with uv

```bash
cd servers/outlook
uv run python -m outlook_mcp.server
```

## Available tools

| Tool | Description |
|------|-------------|
| `search_emails` | Search emails using a query string (supports OData `$search` and `$filter`) |
| `list_emails` | List recent emails from the inbox with optional filtering |
| `read_email` | Read the full content of a specific email by ID |
| `list_calendar_events` | List upcoming calendar events |
| `search_calendar_events` | Search calendar events by subject or other criteria |

## Adding to Claude

1. Start the server (see above)
2. In Claude → **Settings** → **Connectors** → **Add custom connector**
3. Enter `http://localhost:8000/mcp` (or your deployed URL)
4. Follow the OAuth flow to sign in with your Microsoft account
