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
                    if isinstance(data, dict) and "error" in data:
                        return []
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
            if isinstance(data, dict) and "error" in data:
                err = data.get("error") or {}
                if isinstance(err, dict):
                    return {
                        "error": str(err.get("message") or "MCP tool call failed"),
                        "code": err.get("code"),
                        "details": err.get("data"),
                        "tool": name,
                    }
                return {"error": str(err), "tool": name}
            result = data.get("result")
            if isinstance(result, dict) and result.get("isError") is True:
                content = result.get("content")
                message = ""
                if isinstance(content, list):
                    text_parts: List[str] = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            txt = item.get("text")
                            if isinstance(txt, str) and txt.strip():
                                text_parts.append(txt.strip())
                    message = " ".join(text_parts).strip()
                if not message:
                    message = "MCP tool reported an error"
                return {"error": message, "tool": name}
            return result
