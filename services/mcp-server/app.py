import os
import json
import asyncio
import time
from typing import Any, Dict, List, Tuple, Callable
from fastapi import FastAPI
import httpx
from fastmcp import FastMCP

mcp = FastMCP("mcp-server")
mcp_app = mcp.http_app(path="/")
app = FastAPI(lifespan=mcp_app.lifespan)

tool_names: List[str] = []
openapi_loaded = False

@mcp.tool()
async def ping() -> str:
    return "pong"

tool_names.append("ping")

@mcp.tool()
async def add(a: int, b: int) -> int:
    return a + b

tool_names.append("add")

@mcp.tool()
async def sleep_progress(seconds: int, ctx: Any = None) -> str:
    steps = max(1, int(seconds * 2))
    for i in range(steps):
        await asyncio.sleep(0.5)
        if ctx is not None:
            progress = (i + 1) / steps
            if hasattr(ctx, "progress"):
                try:
                    result = ctx.progress(progress, "sleeping")
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass
    return "done"

tool_names.append("sleep_progress")

def load_openapi() -> Tuple[bool, List[str]]:
    path = os.path.join(os.path.dirname(__file__), "openapi.json")
    if not os.path.exists(path):
        return False, []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False, []
    if not isinstance(data, dict) or "paths" not in data:
        return False, []
    api_base = os.getenv("API_BASE_URL")
    if not api_base:
        return False, []
    tools_added: List[str] = []
    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        return False, []

    def register_openapi_tool(name: str, path_template: str, param_names: List[str]) -> None:
        async def handler(**kwargs: Any) -> Dict[str, Any]:
            url = api_base + path_template
            for p in param_names:
                if "{" + p + "}" in url and p in kwargs:
                    url = url.replace("{" + p + "}", str(kwargs[p]))
            params = {k: v for k, v in kwargs.items() if "{" + k + "}" not in path_template}
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url, params=params)
                return {
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": resp.text,
                }
        decorated = mcp.tool(name=name)(handler)
        _ = decorated
        tools_added.append(name)

    for path_template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        op = path_item.get("get")
        if not isinstance(op, dict):
            continue
        operation_id = op.get("operationId")
        if not isinstance(operation_id, str) or not operation_id:
            continue
        params = op.get("parameters", [])
        param_names: List[str] = []
        if isinstance(params, list):
            for p in params:
                if isinstance(p, dict):
                    name = p.get("name")
                    if isinstance(name, str) and name:
                        param_names.append(name)
        register_openapi_tool(operation_id, path_template, param_names)
    return True, tools_added

try:
    if hasattr(mcp, "from_openapi"):
        path = os.path.join(os.path.dirname(__file__), "openapi.json")
        api_base = os.getenv("API_BASE_URL")
        if api_base and os.path.exists(path):
            try:
                mcp.from_openapi(path, base_url=api_base, include_methods=["get"])
                openapi_loaded = True
            except Exception:
                openapi_loaded = False
    else:
        loaded, added = load_openapi()
        if loaded and added:
            openapi_loaded = True
            tool_names.extend(added)
except Exception:
    openapi_loaded = False

app.mount("/mcp", mcp_app)

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}

def current_tools_count() -> int:
    try:
        if hasattr(mcp, "list_tools"):
            tools = mcp.list_tools()
            if isinstance(tools, list):
                return len(tools)
            if isinstance(tools, dict) and "tools" in tools:
                return len(tools.get("tools") or [])
    except Exception:
        pass
    return len(tool_names)

@app.get("/info")
async def info() -> Dict[str, Any]:
    count = current_tools_count()
    return {"toolsCount": count, "openapiLoaded": bool(openapi_loaded)}
