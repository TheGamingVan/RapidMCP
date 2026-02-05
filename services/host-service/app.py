import os
import re
from pathlib import Path
import json
import asyncio
import time
import uuid
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from file_store import FileStore
from gemini_client import GeminiClient
from mcp_http_client import McpHttpClient
from stdio_mcp_client import StdioMcpClient
import httpx

LOG_DIR = Path(__file__).resolve().parents[2] / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "host-service.log"
API_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "api_config.json"

logger = logging.getLogger("host-service")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)

HOST_PORT = int(os.getenv("HOST_PORT", "8080"))
MCP_API_URL = os.getenv("MCP_API_URL", "http://localhost:8000/mcp")
FILE_STORE_DIR = os.getenv("FILE_STORE_DIR", "./data")
FS_MCP_ENABLED = os.getenv("FS_MCP_ENABLED", "true").lower() == "true"
FS_ALLOWED_DIRS = os.getenv("FS_ALLOWED_DIRS", "")

logger.info("HOST_PORT=%s MCP_API_URL=%s FS_MCP_ENABLED=%s FILE_STORE_DIR=%s", HOST_PORT, MCP_API_URL, FS_MCP_ENABLED, FILE_STORE_DIR)

file_store = FileStore(FILE_STORE_DIR)

gemini_client = GeminiClient()

mcp_http = McpHttpClient(MCP_API_URL)
stdio_client = StdioMcpClient(file_store.base_dir)

cached_tools: List[Dict[str, Any]] = []
last_tools_refresh = 0.0
last_fs_tool_names: set[str] = set()
session_conversations: Dict[str, List[Dict[str, Any]]] = {}
session_state: Dict[str, Dict[str, Any]] = {}

def read_api_config() -> Dict[str, str]:
    if not API_CONFIG_PATH.exists():
        return {"apiBaseUrl": "", "bearerToken": "", "geminiApiKey": "", "geminiModel": ""}
    try:
        data = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"apiBaseUrl": "", "bearerToken": "", "geminiApiKey": "", "geminiModel": ""}
        return {
            "apiBaseUrl": str(data.get("apiBaseUrl") or ""),
            "bearerToken": str(data.get("bearerToken") or ""),
            "geminiApiKey": str(data.get("geminiApiKey") or ""),
            "geminiModel": str(data.get("geminiModel") or ""),
        }
    except Exception:
        logger.exception("Failed to read api config")
        return {"apiBaseUrl": "", "bearerToken": "", "geminiApiKey": "", "geminiModel": ""}

def write_api_config(config: Dict[str, str]) -> Dict[str, str]:
    API_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "apiBaseUrl": str(config.get("apiBaseUrl") or ""),
        "bearerToken": str(config.get("bearerToken") or ""),
        "geminiApiKey": str(config.get("geminiApiKey") or ""),
        "geminiModel": str(config.get("geminiModel") or ""),
    }
    tmp_path = API_CONFIG_PATH.with_suffix(API_CONFIG_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        tmp_path.replace(API_CONFIG_PATH)
    except PermissionError:
        # If the file is locked briefly, fall back to overwrite.
        API_CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload

def compute_allowed_dirs() -> List[str]:
    dirs = [os.path.abspath(FILE_STORE_DIR)]
    if FS_ALLOWED_DIRS:
        sep = ";" if os.name == "nt" else ":"
        for p in [p for p in FS_ALLOWED_DIRS.split(sep) if p]:
            dirs.append(os.path.abspath(p))
    return dirs

def is_allowed_path(path: str) -> bool:
    try:
        path_abs = os.path.abspath(path)
        for allowed in compute_allowed_dirs():
            try:
                if os.path.commonpath([path_abs, allowed]) == allowed:
                    return True
            except ValueError:
                continue
    except Exception:
        return False
    return False

@app.on_event("startup")
async def startup() -> None:
    try:
        await file_store.init()
        if FS_MCP_ENABLED:
            await stdio_client.start()
        logger.info("Startup complete")
    except Exception:
        logger.exception("Startup failed")
        raise

@app.on_event("shutdown")
async def shutdown() -> None:
    try:
        await stdio_client.stop()
        logger.info("Shutdown complete")
    except Exception:
        logger.exception("Shutdown failed")

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}

async def resolve_status() -> Dict[str, Any]:
    gemini_ok = gemini_client.is_configured()
    current_model = gemini_client.current_model()
    mcp_ok = await mcp_http.ping()
    fs_ok = stdio_client.is_running
    tools = await get_tools()
    return {
        "gemini": "ok" if gemini_ok else "down",
        "mcpApi": "ok" if mcp_ok else "down",
        "fsMcp": "ok" if fs_ok else "down",
        "model": current_model,
        "toolsCount": len(tools),
    }

@app.get("/status")
async def status() -> Dict[str, Any]:
    return await resolve_status()

@app.get("/config")
async def get_config() -> Dict[str, str]:
    return read_api_config()

@app.post("/config")
async def set_config(payload: Dict[str, Any]) -> Dict[str, str]:
    api_base = payload.get("apiBaseUrl") if isinstance(payload, dict) else ""
    bearer = payload.get("bearerToken") if isinstance(payload, dict) else ""
    gemini_key = payload.get("geminiApiKey") if isinstance(payload, dict) else ""
    gemini_model = payload.get("geminiModel") if isinstance(payload, dict) else ""
    return write_api_config({
        "apiBaseUrl": api_base or "",
        "bearerToken": bearer or "",
        "geminiApiKey": gemini_key or "",
        "geminiModel": gemini_model or "",
    })

@app.get("/gemini/models")
async def list_gemini_models() -> Dict[str, Any]:
    cfg = read_api_config()
    api_key = cfg.get("geminiApiKey") or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return {"models": []}
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    params = {"pageSize": 1000, "key": api_key}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch Gemini models: %s", exc)
        return {"models": []}
    models = []
    for item in data.get("models", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        base = item.get("baseModelId", "")
        methods = item.get("supportedGenerationMethods", []) if isinstance(item, dict) else []
        candidate = base or name
        if isinstance(candidate, str) and candidate.startswith("models/"):
            candidate = candidate.replace("models/", "", 1)
        if not isinstance(candidate, str) or not candidate:
            continue
        lower = candidate.lower()
        if any(token in lower for token in ("image", "audio", "tts", "embedding")):
            continue
        if isinstance(methods, list) and methods and "generateContent" not in methods and "streamGenerateContent" not in methods:
            continue
        models.append(candidate)
    models = sorted(set(models))
    return {"models": models}

async def get_tools() -> List[Dict[str, Any]]:
    global cached_tools, last_tools_refresh, last_fs_tool_names
    now = time.time()
    if now - last_tools_refresh < 30 and cached_tools:
        return cached_tools
    tools: List[Dict[str, Any]] = []
    api_tools = await mcp_http.tools_list()
    for t in api_tools:
        tools.append({
            "name": "api." + t.get("name", ""),
            "description": t.get("description", ""),
            "inputSchema": t.get("inputSchema", {}),
            "source": "api",
        })
    fs_tools = []
    if FS_MCP_ENABLED and stdio_client.is_running:
        try:
            fs_tools = await stdio_client.tools_list()
        except Exception as exc:
            logger.warning("fs MCP tools_list failed: %s", exc)
            fs_tools = []
    last_fs_tool_names = {t.get("name", "") for t in fs_tools if isinstance(t, dict)}
    for t in fs_tools:
        tools.append({
            "name": "fs." + t.get("name", ""),
            "description": t.get("description", ""),
            "inputSchema": t.get("inputSchema", {}),
            "source": "fs",
        })
    tools.append({
        "name": "http.put",
        "description": "Upload a local file to a URL via HTTP PUT. Use for S3 signed URLs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Destination URL (e.g., signed S3 URL)."},
                "filePath": {"type": "string", "description": "Local path to the file to upload."},
                "contentType": {"type": "string", "description": "Optional Content-Type header."}
            },
            "required": ["url", "filePath"]
        },
        "source": "host",
    })
    if "delete_file" not in last_fs_tool_names:
        tools.append({
            "name": "fs.delete_file",
            "description": "Delete a file at the given path.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "source": "fs",
        })
    cached_tools = tools
    last_tools_refresh = now
    return tools

@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": await get_tools()}

@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    return await file_store.save_upload(file)

@app.get("/files")
async def files() -> Dict[str, Any]:
    return {"files": await file_store.list_files()}

@app.delete("/files/{file_id}")
async def delete_file(file_id: str) -> Dict[str, Any]:
    ok = await file_store.delete_file(file_id)
    return {"deleted": ok}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    session_id = None
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                logger.warning("Invalid WS JSON: %s", msg)
                continue
            msg_type = data.get("type")
            if msg_type == "hello":
                session_id = data.get("sessionId")
                if session_id and session_id not in session_conversations:
                    session_conversations[session_id] = []
                    session_state[session_id] = {}
                status_payload = await resolve_status()
                await ws.send_text(json.dumps({"type": "status", **status_payload}))
            elif msg_type == "user_message":
                session_id = data.get("sessionId")
                content = data.get("content", "")
                file_uris = data.get("fileUris", [])
                config_override = data.get("config")
                await handle_user_message(ws, session_id, content, file_uris, config_override)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("WebSocket error session=%s", session_id)

async def handle_user_message(
    ws: WebSocket,
    session_id: Optional[str],
    content: str,
    file_uris: List[str],
    config_override: Optional[Dict[str, Any]] = None,
) -> None:
    tools = await get_tools()
    status_payload = await resolve_status()
    await ws.send_text(json.dumps({"type": "status", **status_payload}))
    tool_names = {t.get("name", "") for t in tools}
    content_text = content or ""
    api_tools = [t for t in tools if t.get("source") == "api"]
    memory = session_conversations.get(session_id, []) if session_id else []
    state = session_state.get(session_id, {}) if session_id else {}
    normalized_override: Dict[str, str] | None = None
    if isinstance(config_override, dict):
        normalized_override = {
            "geminiApiKey": str(config_override.get("geminiApiKey") or ""),
            "geminiModel": str(config_override.get("geminiModel") or ""),
        }
        state["apiConfig"] = normalized_override
        if session_id is not None:
            session_state[session_id] = state
    elif isinstance(state.get("apiConfig"), dict):
        normalized_override = {
            "geminiApiKey": str(state.get("apiConfig", {}).get("geminiApiKey") or ""),
            "geminiModel": str(state.get("apiConfig", {}).get("geminiModel") or ""),
        }

    async def run_tool_ws(name: str, arguments: Dict[str, Any]) -> Any:
        call_id = str(uuid.uuid4())
        await ws.send_text(json.dumps({"type": "tool_start", "callId": call_id, "name": name, "arguments": arguments}))
        try:
            result = await call_tool(name, arguments)
            await ws.send_text(json.dumps({"type": "tool_end", "callId": call_id, "result": result}))
            return result
        except Exception as e:
            await ws.send_text(json.dumps({"type": "tool_error", "callId": call_id, "error": str(e)}))
            raise

    def compute_allowed_dirs() -> List[str]:
        dirs = [os.path.abspath(FILE_STORE_DIR)]
        if FS_ALLOWED_DIRS:
            sep = ";" if os.name == "nt" else ":"
            for p in [p for p in FS_ALLOWED_DIRS.split(sep) if p]:
                dirs.append(os.path.abspath(p))
        return dirs

    def default_fs_dir() -> str:
        dirs = compute_allowed_dirs()
        return dirs[0] if dirs else os.path.abspath(FILE_STORE_DIR)

    def extract_entries(list_result: Any) -> List[Any]:
        if isinstance(list_result, list):
            return list_result
        if isinstance(list_result, dict):
            # FS MCP returns a "content" array with a text listing; parse it.
            if "content" in list_result and isinstance(list_result.get("content"), list):
                for item in list_result.get("content"):
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        if isinstance(text, str) and text:
                            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                            names: List[str] = []
                            for ln in lines:
                                # Expect lines like "[FILE] foo.txt"
                                if "]" in ln:
                                    _, rest = ln.split("]", 1)
                                    name = rest.strip()
                                    if name:
                                        names.append(name)
                            if names:
                                return names
            # Some variants return a nested structuredContent string; parse it too.
            if "structuredContent" in list_result and isinstance(list_result.get("structuredContent"), dict):
                sc = list_result.get("structuredContent", {})
                text = sc.get("content") if isinstance(sc, dict) else None
                if isinstance(text, str) and text:
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    names: List[str] = []
                    for ln in lines:
                        if "]" in ln:
                            _, rest = ln.split("]", 1)
                            name = rest.strip()
                            if name:
                                names.append(name)
                    if names:
                        return names
            for key in ("entries", "items", "files", "children"):
                entries = list_result.get(key)
                if isinstance(entries, list):
                    return entries
                if isinstance(entries, dict):
                    # Convert mapping to list-like entries
                    return [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in entries.items()]
        return []

    def extract_target_dir(text: str) -> str | None:
        # Match Windows absolute paths with optional trailing punctuation.
        match = re.search(r"([A-Za-z]:\\[^\\:*?\"<>|]+(?:\\[^\\:*?\"<>|]+)*)", text)
        if match:
            return match.group(1).rstrip(" .")
        return None

    def extract_filename(text: str) -> Optional[str]:
        match = re.search(r"\b([A-Za-z0-9_.-]+)\.(txt|json|md)\b", text, re.IGNORECASE)
        if match:
            return match.group(0)
        return None

    can_write_files = "fs.write_file" in tool_names

    def summarize_result(result: Any) -> str:
        if isinstance(result, dict) and "status_code" in result and "body" in result:
            status = result.get("status_code")
            body = result.get("body")
            parsed = None
            if isinstance(body, str):
                try:
                    parsed = json.loads(body)
                except Exception:
                    parsed = None
            if isinstance(parsed, dict):
                keys = ", ".join(sorted(parsed.keys()))
                items = parsed.get("items")
                count = len(items) if isinstance(items, list) else None
                parts = [f"Status {status}. JSON object with keys: {keys}."]
                if count is not None:
                    parts.append(f"Items count: {count}.")
                return " ".join(parts)
            if isinstance(parsed, list):
                return f"Status {status}. JSON array with {len(parsed)} item(s)."
            if isinstance(body, str) and body:
                snippet = body.strip().replace("\n", " ")
                snippet = snippet[:200] + ("…" if len(snippet) > 200 else "")
                return f"Status {status}. Body: {snippet}"
            return f"Status {status}. Empty body."
        if isinstance(result, dict):
            keys = ", ".join(sorted(result.keys()))
            return f"JSON object with keys: {keys}."
        if isinstance(result, list):
            return f"JSON array with {len(result)} item(s)."
        return str(result)

    def default_args_for_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
        name = tool.get("name", "")
        short = name[len("api."):] if name.startswith("api.") else name
        if short == "get_widget":
            return {"widget_id": "w1"}
        if short == "search_widgets":
            return {"q": "alpha"}
        if short == "list_widgets":
            return {"limit": 5}
        schema = tool.get("inputSchema") or {}
        props = schema.get("properties") if isinstance(schema, dict) else None
        required = schema.get("required") if isinstance(schema, dict) else None
        args: Dict[str, Any] = {}
        if isinstance(required, list) and isinstance(props, dict):
            for key in required:
                prop = props.get(key, {}) if isinstance(props, dict) else {}
                ptype = prop.get("type") if isinstance(prop, dict) else None
                if ptype == "integer":
                    args[key] = 1
                elif ptype == "number":
                    args[key] = 1
                elif ptype == "boolean":
                    args[key] = False
                else:
                    args[key] = "test"
        return args

    def stringify_tool_output(result: Any) -> str:
        if isinstance(result, dict) and "body" in result:
            body = result.get("body")
            if isinstance(body, str):
                try:
                    parsed = json.loads(body)
                    return json.dumps(parsed, indent=2)
                except Exception:
                    return body
            return json.dumps(body, indent=2) if body is not None else ""
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2)
        return str(result)

    conversation: List[Dict[str, Any]] = list(memory)
    if content_text:
        conversation.append({"role": "user", "content": content_text})
    used_fs_write = False
    last_tool_result: Any = None
    last_tool_name: Optional[str] = None
    max_iters = 12
    for i in range(max_iters):
        decision = await gemini_client.decide(conversation, tools, "", file_uris, config_override=normalized_override)
        decision_type = decision.get("type")
        if decision_type not in ("tool", "final"):
            logger.warning("Model returned invalid decision type: %s", decision)
            message = "Model returned an invalid response. Please try again."
            await emit_assistant_message(ws, message)
            if session_id is not None:
                session_conversations[session_id] = conversation + [{"role": "assistant", "content": message}]
            return
        if decision_type == "tool":
            name = decision.get("name", "")
            if not isinstance(name, str) or not name:
                logger.warning("Model returned tool call without name: %s", decision)
                message = "Model returned an invalid tool call. Please try again."
                await emit_assistant_message(ws, message)
                if session_id is not None:
                    session_conversations[session_id] = conversation + [{"role": "assistant", "content": message}]
                return
            arguments = decision.get("arguments", {})
            call_id = str(uuid.uuid4())
            conversation.append({"role": "assistant", "content": json.dumps({"tool": name, "arguments": arguments})})
            await ws.send_text(json.dumps({"type": "tool_start", "callId": call_id, "name": name, "arguments": arguments}))
            try:
                result = await call_tool(name, arguments)
                await ws.send_text(json.dumps({"type": "tool_end", "callId": call_id, "result": result}))
                if name.startswith("fs.") and re.search(r"write|save", name, re.IGNORECASE):
                    used_fs_write = True
                last_tool_result = result
                last_tool_name = name
                conversation.append({"role": "tool", "name": name, "content": json.dumps(result)})
                if not gemini_client.is_configured(normalized_override):
                    summary = summarize_result(result)
                    message = f"Done. {summary}"
                    await emit_assistant_message(ws, message)
                    if session_id is not None:
                        session_conversations[session_id] = conversation + [{"role": "assistant", "content": message}]
                    return
                content = ""
                continue
            except Exception as e:
                await ws.send_text(json.dumps({"type": "tool_error", "callId": call_id, "error": str(e)}))
                conversation.append({"role": "tool", "name": name, "content": str(e)})
                content = ""
                continue
        message = decision.get("message", "")
        if not isinstance(message, str) or not message.strip():
            logger.warning("Model returned empty message: %s", decision)
            message = "Model returned an empty response. Please try again."
        await emit_assistant_message(ws, message)
        if session_id is not None:
            session_conversations[session_id] = conversation + [{"role": "assistant", "content": message}]
        return

    # Fallback: if we exhaust iterations, return a safe message.
    await emit_assistant_message(
        ws,
        "I couldn't finish the task within the allowed steps. Please try again.",
    )
    if session_id is not None:
        session_conversations[session_id] = conversation + [
            {"role": "assistant", "content": "I couldn't finish the task within the allowed steps. Please try again."},
        ]

async def emit_assistant_message(ws: WebSocket, message: str) -> None:
    chunk_size = 40
    for i in range(0, len(message), chunk_size):
        delta = message[i:i+chunk_size]
        await ws.send_text(json.dumps({"type": "assistant_delta", "content": delta}))
        await asyncio.sleep(0.01)
    await ws.send_text(json.dumps({"type": "assistant_message", "content": message}))

async def call_tool(name: str, arguments: Dict[str, Any]) -> Any:
    if name.startswith("fs."):
        real_name = name[len("fs."):]
        if real_name == "delete_file":
            target = arguments.get("path")
            if not isinstance(target, str) or not target:
                return {"error": "invalid_path"}
            if not is_allowed_path(target):
                return {"error": "path_not_allowed"}
            if not os.path.exists(target):
                return {"deleted": False, "reason": "not_found"}
            if os.path.isdir(target):
                return {"error": "path_is_directory"}
            try:
                os.remove(target)
                return {"deleted": True, "path": target}
            except Exception as e:
                return {"deleted": False, "error": str(e)}
        return await stdio_client.tools_call(real_name, arguments)
    if name.startswith("api."):
        real_name = name[len("api."):]
        return await mcp_http.tools_call(real_name, arguments)
    if name == "http.put":
        url = arguments.get("url")
        file_path = arguments.get("filePath")
        content_type = arguments.get("contentType") or "application/octet-stream"
        if not isinstance(url, str) or not url:
            return {"error": "invalid_url"}
        if not isinstance(file_path, str) or not file_path:
            return {"error": "invalid_file_path"}
        if not is_allowed_path(file_path):
            return {"error": "path_not_allowed"}
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            return {"error": "file_not_found"}
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.put(url, content=data, headers={"Content-Type": content_type})
            return {
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp.text,
            }
        except Exception as e:
            return {"error": str(e)}
    return {"error": "unknown_tool"}
