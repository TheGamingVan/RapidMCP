import json
import os
from typing import Any, Dict, Optional, Tuple

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

app = FastAPI(title="Dummy RapidPipeline API", version="1.0.0")


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}


def _load_openapi() -> Optional[Dict[str, Any]]:
    spec_path = os.path.join(os.path.dirname(__file__), "..", "mcp-server", "openapi.yml")
    spec_path = os.path.abspath(spec_path)
    if not os.path.exists(spec_path):
        return None
    with open(spec_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or "paths" not in data:
        return None
    return data


def _pick_response(responses: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    if not isinstance(responses, dict) or not responses:
        return 200, {}
    for preferred in ("200", "201", "202", "204"):
        if preferred in responses:
            return int(preferred), responses.get(preferred) or {}
    first_key = next(iter(responses))
    try:
        code = int(first_key)
    except Exception:
        code = 200
    return code, responses.get(first_key) or {}


def _extract_example(response_spec: Dict[str, Any]) -> Tuple[Optional[str], Any]:
    if not isinstance(response_spec, dict):
        return None, None
    content = response_spec.get("content")
    if not isinstance(content, dict):
        return None, None
    for content_type, content_spec in content.items():
        if not isinstance(content_spec, dict):
            continue
        if "example" in content_spec:
            return content_type, content_spec.get("example")
        schema = content_spec.get("schema")
        if isinstance(schema, dict) and "example" in schema:
            return content_type, schema.get("example")
    return None, None


def _coerce_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            try:
                return json.loads(text)
            except Exception:
                return value
    return value


def _make_handler(path_template: str, method: str, responses: Dict[str, Any]):
    status_code, response_spec = _pick_response(responses)
    content_type, example = _extract_example(response_spec)
    example = _coerce_json(example)

    async def handler(request: Request, **path_params: Any):
        if status_code == 204:
            return Response(status_code=204)
        if content_type and content_type.startswith("text/plain"):
            body = "" if example is None else str(example)
            return PlainTextResponse(content=body, status_code=status_code)
        if example is not None:
            return JSONResponse(content=example, status_code=status_code)
        payload = {
            "dummy": True,
            "path": path_template,
            "method": method,
            "path_params": path_params,
            "query_params": dict(request.query_params),
        }
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload["body"] = await request.json()
            except Exception:
                payload["body"] = None
        return JSONResponse(content=payload, status_code=status_code)

    return handler


def _register_routes() -> int:
    data = _load_openapi()
    if not data:
        return 0
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return 0
    registered = 0
    for path_template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() not in {"get", "post", "delete", "put", "patch"}:
                continue
            if not isinstance(op, dict):
                continue
            responses = op.get("responses") or {}
            handler = _make_handler(path_template, method.upper(), responses)
            app.add_api_route(
                path_template,
                handler,
                methods=[method.upper()],
                name=op.get("operationId") or f"{method}_{path_template}",
            )
            registered += 1
    return registered


_REGISTERED_ROUTES = _register_routes()
