import os
import json
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
import httpx
from fastmcp import FastMCP
from fastmcp.server.openapi.components import OpenAPITool
from fastmcp.utilities.openapi.models import HTTPRoute

logger = logging.getLogger("mcp-server.openapi")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)


def _config_path() -> Path:
    override = os.getenv("API_CONFIG_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "config" / "api_config.json"


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


class DynamicConfigClient:
    def __init__(self, config_loader, default_base_url: Optional[str]) -> None:
        self._client = httpx.AsyncClient(timeout=20.0)
        self._config_loader = config_loader
        self._default_base_url = default_base_url or "http://localhost"

    @property
    def base_url(self) -> httpx.URL:
        runtime = self._config_loader()
        api_base = (
            runtime.get("apiBaseUrl")
            or os.getenv("API_BASE_URL")
            or self._default_base_url
        )
        try:
            return httpx.URL(api_base)
        except Exception:
            return httpx.URL(self._default_base_url)

    @property
    def headers(self) -> httpx.Headers:
        runtime = self._config_loader()
        token = runtime.get("bearerToken") or os.getenv("API_BEARER_TOKEN")
        headers = httpx.Headers()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def send(self, request: httpx.Request) -> httpx.Response:
        try:
            return await self._client.send(request)
        except httpx.ConnectError as exc:
            raise ValueError(
                f"Connection failed for {request.method} {request.url}. "
                "Check API_BASE_URL/API_CONFIG_PATH and that the API host is running."
            ) from exc

    async def aclose(self) -> None:
        await self._client.aclose()


openapi_loaded = False
openapi_error: Optional[str] = None
openapi_exception: Optional[str] = None


def customize_openapi_component(route: HTTPRoute, component: Any) -> None:
    # Some optimize endpoints may return empty/non-object bodies on success or edge cases.
    # Disable strict output schema for these tools so FastMCP surfaces real API/tool errors
    # instead of secondary "Output validation error" messages.
    if isinstance(component, OpenAPITool):
        op_id = (route.operation_id or "").lower()
        path = (route.path or "").lower()
        if op_id in {"optimize", "multioptimize"} or "/rawmodel/optimize" in path:
            component.output_schema = None

openapi_spec = read_openapi()
try:
    if not openapi_spec:
        raise ValueError("OpenAPI spec missing or invalid.")
    default_api_base = resolve_api_base(openapi_spec)
    client = DynamicConfigClient(load_runtime_config, default_api_base)
    mcp = FastMCP.from_openapi(
        openapi_spec,
        client=client,
        name="mcp-server",
        mcp_component_fn=customize_openapi_component,
    )
    openapi_loaded = True
except Exception as exc:
    openapi_error = "Failed to initialize FastMCP from OpenAPI."
    openapi_exception = f"{type(exc).__name__}: {exc}"
    logger.exception("OpenAPI load crashed.")
    mcp = FastMCP("mcp-server")

# Use JSON responses + stateless HTTP so simple HTTP clients can talk to MCP.
mcp_app = mcp.http_app(path="/", json_response=True, stateless_http=True)
app = FastAPI(lifespan=mcp_app.lifespan)
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
    return 0


@app.get("/info")
async def info() -> Dict[str, Any]:
    count = current_tools_count()
    return {
        "toolsCount": count,
        "openapiLoaded": bool(openapi_loaded),
        "openapiError": openapi_error,
        "openapiException": openapi_exception,
    }
