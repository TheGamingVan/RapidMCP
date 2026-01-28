import os
import json
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from fastapi import FastAPI
import httpx
from fastmcp import FastMCP

mcp = FastMCP("mcp-server")
# Use JSON responses + stateless HTTP so simple HTTP clients can talk to MCP.
mcp_app = mcp.http_app(path="/", json_response=True, stateless_http=True)
app = FastAPI(lifespan=mcp_app.lifespan)

tool_names: List[str] = []
openapi_loaded = False
openapi_error: Optional[str] = None
openapi_exception: Optional[str] = None

logger = logging.getLogger("mcp-server.openapi")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

def _config_path() -> Path:
    default = Path(__file__).resolve().parents[2] / "data" / "api_config.json"
    override = os.getenv("API_CONFIG_PATH")
    return Path(override) if override else default

def load_runtime_config() -> Dict[str, str]:
    path = _config_path()
    if not path.exists():
        return {"apiBaseUrl": "", "bearerToken": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"apiBaseUrl": "", "bearerToken": ""}
        return {
            "apiBaseUrl": str(data.get("apiBaseUrl") or ""),
            "bearerToken": str(data.get("bearerToken") or ""),
        }
    except Exception:
        logger.exception("Failed to read api config")
        return {"apiBaseUrl": "", "bearerToken": ""}


def read_openapi() -> Optional[Dict[str, Any]]:
    path = os.path.join(os.path.dirname(__file__), "openapi.yml")
    if not os.path.exists(path):
        logger.error("OpenAPI spec missing at %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        logger.exception("Failed to read OpenAPI spec at %s", path)
        return None
    if not isinstance(data, dict) or "paths" not in data:
        logger.error("OpenAPI spec missing 'paths' at %s", path)
        return None
    return data

def resolve_api_base(data: Dict[str, Any]) -> Optional[str]:
    runtime = load_runtime_config()
    api_base = runtime.get("apiBaseUrl") or os.getenv("API_BASE_URL")
    if api_base:
        return api_base
    servers = data.get("servers")
    if isinstance(servers, list) and servers:
        first = servers[0]
        if isinstance(first, dict):
            url = first.get("url")
            if isinstance(url, str) and url:
                return url
    return None

def load_openapi() -> Tuple[bool, List[str]]:
    data = read_openapi()
    if not data:
        return False, []
    default_api_base = resolve_api_base(data)
    if not default_api_base:
        logger.error("API base URL not set (API_BASE_URL, config file, or servers[0].url).")
        return False, []
    tools_added: List[str] = []
    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        return False, []

    def register_openapi_tool(name: str, path_template: str, param_names: List[str]) -> None:
        safe_params = [p for p in param_names if isinstance(p, str) and p.isidentifier()]
        params_sig = ", ".join([f"{p}: Any = None" for p in safe_params])
        lines = [f"async def handler({params_sig}):"] if params_sig else ["async def handler():"]
        lines.append("    runtime = load_runtime_config()")
        lines.append("    api_base = runtime.get(\"apiBaseUrl\") or default_api_base")
        lines.append("    token = runtime.get(\"bearerToken\") or os.getenv(\"API_BEARER_TOKEN\")")
        lines.append("    if not api_base:")
        lines.append("        return {\"status_code\": 500, \"headers\": {}, \"body\": \"API base URL not configured\"}")
        lines.append("    url = api_base + path_template")
        for p in safe_params:
            lines.append(f"    if \"{{{p}}}\" in url and {p} is not None:")
            lines.append(f"        url = url.replace(\"{{{p}}}\", str({p}))")
        lines.append("    params = {}")
        for p in safe_params:
            lines.append(f"    if \"{{{p}}}\" not in path_template and {p} is not None:")
            lines.append(f"        params[\"{p}\"] = {p}")
        lines.append("    headers = {}")
        lines.append("    if token:")
        lines.append("        headers[\"Authorization\"] = f\"Bearer {token}\"")
        lines.append("    async with httpx.AsyncClient(timeout=20) as client:")
        lines.append("        resp = await client.get(url, params=params, headers=headers)")
        lines.append("        return {")
        lines.append("            \"status_code\": resp.status_code,")
        lines.append("            \"headers\": dict(resp.headers),")
        lines.append("            \"body\": resp.text,")
        lines.append("        }")

        namespace: Dict[str, Any] = {
            "default_api_base": default_api_base,
            "path_template": path_template,
            "httpx": httpx,
            "Any": Any,
            "os": os,
            "load_runtime_config": load_runtime_config,
        }
        code = "\n".join(lines)
        exec(code, namespace)
        handler = namespace["handler"]
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
    data = read_openapi()
    path = os.path.join(os.path.dirname(__file__), "openapi.yml")
    api_base = resolve_api_base(data) if data else None
    if api_base and data and os.path.exists(path):
        loaded, added = load_openapi()
        if loaded and added:
            openapi_loaded = True
            tool_names.extend(added)
            openapi_error = None
            openapi_exception = None
            logger.info("Loaded OpenAPI via manual loader: %s", ", ".join(added))
        else:
            openapi_error = "Manual OpenAPI loader did not register any tools."
            logger.error("%s", openapi_error)
    else:
        openapi_error = "Missing API base or OpenAPI spec."
        logger.error("OpenAPI not loaded: %s", openapi_error)
        openapi_loaded = False
except Exception as exc:
    openapi_error = "Unhandled exception during OpenAPI load."
    openapi_exception = f"{type(exc).__name__}: {exc}"
    logger.exception("OpenAPI load crashed.")
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
    return {
        "toolsCount": count,
        "openapiLoaded": bool(openapi_loaded),
        "openapiError": openapi_error,
        "openapiException": openapi_exception,
    }
