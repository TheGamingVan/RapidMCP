import asyncio
import json
from typing import Any, Dict, List
import httpx

class McpHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        # FastMCP requires clients to accept JSON + SSE for StreamableHTTP.
        self._headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(
                    self.base_url,
                    json={"jsonrpc": "2.0", "id": 0, "method": "tools/list", "params": {}},
                    headers=self._headers,
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def tools_list(self) -> List[Dict[str, Any]]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(self.base_url, json=payload, headers=self._headers)
                    resp.raise_for_status()
                    data = resp.json()
                    return data.get("result", {}).get("tools", [])
            except Exception:
                await asyncio.sleep(0.3)
        return []

    async def tools_call(self, name: str, arguments: Dict[str, Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.base_url, json=payload, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result")
