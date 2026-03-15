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

Graph API access uses [DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.aio.defaultazurecredential). Register an application in [Microsoft Entra ID](https://portal.azure.com) with **application** permissions `Mail.Read` and `Calendars.Read` (admin consent required), then set:

```env
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<app-client-id>
AZURE_CLIENT_SECRET=<app-client-secret>
GRAPH_USER=user@example.com   # UPN or object ID of the mailbox to access
SERVER_URL=https://your-server.example.com
```

`DefaultAzureCredential` also supports Managed Identity and workload identity.

## Running

```bash
docker build -t mcp-servers .
docker run -p 8000:8000 \
  -e AZURE_TENANT_ID=... \
  -e AZURE_CLIENT_ID=... \
  -e AZURE_CLIENT_SECRET=... \
  -e GRAPH_USER=user@example.com \
  -e SERVER_URL=https://your-server.example.com \
  mcp-servers
```

## Adding to Claude

1. Go to **Claude** → **Settings** → **Connectors** → **Add custom connector**
2. Enter `https://your-server.example.com/mcp`
3. Claude will register via DCR and guide you through the OAuth flow