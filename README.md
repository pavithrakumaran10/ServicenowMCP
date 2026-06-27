# ServiceNow Developer Actions — MCP Server

An [MCP](https://modelcontextprotocol.io) server that connects Claude Desktop (or any MCP client) to a ServiceNow instance, exposing **guarded developer actions** as natural-language tools. Claude can read incidents, inspect CMDB and table schemas, and create records — with every write isolated to a scoped Update Set, restricted to an allowlist of tables, and protected by a dry-run preview.

Built with **FastMCP**, a typed REST client, and an explicit guardrail layer — the difference between an LLM API wrapper and an agent tool you'd let near a production instance.

---

## Why this project

This demonstrates two skill sets at once:

- **AI engineering / agent architecture** — agentic tool design with safety rails: input schemas (Pydantic), an allowlist + blocklist for writable tables, automatic Update Set scoping, and a `dry_run` mode on risky tools so the model previews intent before mutating anything.
- **ServiceNow integration architecture** — a resilient Table API client with OAuth2 (with Basic-auth fallback), token refresh on 401, and exponential backoff on 429/5xx, plus CMDB and `sys_dictionary` introspection tools.

---

## Architecture

```
Claude Desktop
   │  (MCP protocol over stdio)
   ▼
FastMCP Server  ── server.py
   │
   ├── tools (read)   get_incidents · query_table · describe_table · get_cmdb_cis
   ├── tools (write)  create_incident · create_script_include   ← guarded
   │
   ├── guardrails.py  allowlist · blocklist · update-set scoping · dry-run
   ▼
ServiceNowClient  ── client.py   (OAuth2 / Basic · retry · backoff · typed errors)
   │  REST (Table API)
   ▼
ServiceNow instance (PDI)
```

## Tools

| Tool                    | Type  | Notes                                     |
| ----------------------- | ----- | ----------------------------------------- |
| `get_incidents`         | read  | Newest-first, active filter               |
| `query_table`           | read  | GlideRecord-style query on any table      |
| `describe_table`        | read  | Field inspection via `sys_dictionary`     |
| `get_cmdb_cis`          | read  | List CIs from a CMDB class                |
| `create_incident`       | write | Allowlisted, Update-Set scoped, `dry_run` |
| `create_script_include` | write | `dry_run=True` by default                 |

## Guardrails

1. **Writable allowlist** — only dev-artifact tables (`incident`, `sys_script_include`, `sys_script`, …). Security/identity tables (`sys_user`, `sys_security_acl`, …) are explicitly blocked.
2. **Update Set scoping** — every write lands in a named, reviewable Update Set, never in Default.
3. **Dry-run** — risky tools echo what _would_ happen instead of executing.

---

## Setup

```bash
git clone <your-repo-url> && cd servicenow-mcp
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env        # fill in your PDI URL + credentials
pytest                      # 6 tests, all green
```

### Connect to Claude Desktop

Add to `claude_desktop_config.json` (Developer → Open App Configuration File), then restart:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp.server"],
      "cwd": "/absolute/path/to/servicenow-mcp/src",
      "env": {
        "SN_URL": "https://dev385830.service-now.com/",
        "SN_USER": "claudeuser",
        "SN_PASS": "wL}oW2DWSWr@Y^g$gj.YL]j}hX[mJZsnq4^j=k@Vhr],?XK8F<i2-aXe+A54>MK]MOn?8b8$Ig7hx:aC%dyyv%y=]E]oB1mX#zpA",
        "SN_UPDATE_SET": "MCP Automated Changes"
      }
    }
  }
}
```

A 🔧 indicator confirms the tools loaded. Then try:

> "Show me the 5 newest active incidents"
> "Describe the cmdb_ci_server table"
> "Create an incident: VPN gateway down, urgency high — dry run first"

---

## Tech

Python 3.10+ · FastMCP · Pydantic v2 · requests · pytest + responses

## Roadmap

- OAuth client-credentials grant (service account)
- `commit_to_source_control` tool wrapping Studio's Git integration
- Read-through cache for schema/CMDB lookups
- Structured audit log of every write the server performs

---

_Author: Pavithra Kumaran S — ServiceNow Senior Consultant exploring AI agent architecture._
