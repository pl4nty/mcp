# mcp-servers

Remote MCP server for Microsoft 365 built with the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), designed to work with [Claude custom connectors](https://support.claude.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers).

## Structure

```
mcp-servers/
├── Dockerfile
├── pyproject.toml
├── README.md
├── server.py          # FastMCP server with OAuth 2.1 + DCR
└── outlook/
    ├── mail.py        # search_emails, list_emails, read_email
    └── calendar.py    # list_calendar_events, search_calendar_events
```

## Tools

| Tool | Description |
|------|-------------|
| `search_emails` | Free-text search over the user's mailbox |
| `list_emails` | List emails from a folder with optional unread and date-range filters |
| `read_email` | Read the full content of a specific email by ID |
| `list_calendar_events` | List calendar events with optional date-range filter |
| `search_calendar_events` | Search calendar events by subject or body text |

## Configuration

Register an application in [Microsoft Entra ID](https://portal.azure.com) with **delegated** permissions `Mail.Read` and `Calendars.Read`. Set the redirect URI to `{SERVER_URL}/auth/callback`.

```env
ENTRA_TENANT_ID=common        # or your specific tenant ID
ENTRA_CLIENT_ID=<app-client-id>
ENTRA_CLIENT_SECRET=<app-client-secret>
SERVER_URL=https://your-server.example.com
```

Using `common` as the tenant ID supports both personal Microsoft accounts and work/school accounts.

## Running

```bash
docker build -t mcp-servers .
docker run -p 8000:8000 \
  -e ENTRA_TENANT_ID=common \
  -e ENTRA_CLIENT_ID=... \
  -e ENTRA_CLIENT_SECRET=... \
  -e SERVER_URL=https://your-server.example.com \
  mcp-servers
```

## Adding to Claude

1. Go to **Claude** → **Settings** → **Connectors** → **Add custom connector**
2. Enter `https://your-server.example.com/mcp`
3. Claude registers via DCR and redirects you to sign in with your Microsoft account
4. After signing in, Claude uses your delegated token to call Graph API as `/me`