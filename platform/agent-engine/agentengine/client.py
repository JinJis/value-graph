"""Platform client — fetch the tool catalog and call tools through the gateway.

Tool calls carry the tenant API key, so the control plane enforces entitlement +
metering + audit (the agent can only use what the tenant activated).
"""

from __future__ import annotations

import httpx

from agentengine.config import settings


class PlatformClient:
    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key

    async def fetch_tools(self) -> dict[str, dict]:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(f"{settings.gateway_url}/catalog")
            resp.raise_for_status()
            connectors = resp.json().get("connectors", [])
        tools: dict[str, dict] = {}
        for con in connectors:
            for res in con.get("resources", []):
                name = f"{con['id']}__{res['name']}"
                tools[name] = {
                    "name": name,
                    "connector": con["id"],
                    "method": res.get("method", "GET").upper(),
                    "path": res["path"],
                    "params": res.get("params", []),
                    "description": res.get("description", ""),
                    "source": (res.get("provenance") or {}).get("source"),
                }
        return tools

    async def call_tool(self, tool: dict, args: dict) -> dict:
        headers = {"X-API-KEY": self.api_key} if self.api_key else {}
        url = f"{settings.gateway_url}{tool['path']}"
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            if tool["method"] == "GET":
                resp = await client.get(url, params=args, headers=headers)
            else:
                resp = await client.request(tool["method"], url, json=args, headers=headers)
        try:
            data = resp.json()
        except ValueError:
            data = resp.text[:1000]
        return {"status": resp.status_code, "connector": resp.headers.get("x-connector"), "data": data}
