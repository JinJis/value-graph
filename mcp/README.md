# MCP Server

Exposes the platform's data connectors to AI agents as **MCP tools**. Tools are generated from the
data-plane `/catalog` and routed through the **control-plane gateway** with a tenant API key — so
**entitlement (activation), metering, and audit are enforced** for every agent call.

```
agent (MCP client) ─▶ this MCP server ─▶ control-plane gateway ─▶ datasets data plane
```

Tools are named `{connector}__{resource}`, e.g. `sec_edgar__company_facts`, `yahoo__prices`,
`fred__interest_rates`. Each tool's description carries its **provenance source + license**. Calling a
connector the tenant hasn't activated returns the gateway's `403` in the result (honest, not hidden).

## Configure in an MCP client

```jsonc
{
  "mcpServers": {
    "valuegraph-data": {
      "command": "uv",
      "args": ["run", "--directory", "/abs/path/mcp", "python", "-m", "mcpserver.server"],
      "env": {
        "MCP_GATEWAY_URL": "http://127.0.0.1:8010",   // the control-plane gateway
        "MCP_API_KEY": "vgk_...."                       // this tenant's key
      }
    }
  }
}
```

The agent then sees only the data behind the tenant's activated connectors, and every call is metered.

## Dev

```bash
cd mcp
uv sync --extra dev
uv run pytest -q
MCP_GATEWAY_URL=http://127.0.0.1:8010 MCP_API_KEY=vgk_... uv run python -m mcpserver.server
```
