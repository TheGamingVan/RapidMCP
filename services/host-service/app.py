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

LOG_DIR = Path(__file__).resolve().parents[2] / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "host-service.log"

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
FILE_STORE_DIR = os.getenv("FILE_STORE_DIR", "./services/host-service/files")
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
    mcp_ok = await mcp_http.ping()
    fs_ok = stdio_client.is_running
    tools = await get_tools()
    return {
        "gemini": "ok" if gemini_ok else "down",
        "mcpApi": "ok" if mcp_ok else "down",
        "fsMcp": "ok" if fs_ok else "down",
        "model": gemini_client.model_name,
        "toolsCount": len(tools),
    }

@app.get("/status")
async def status() -> Dict[str, Any]:
    return await resolve_status()

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
        fs_tools = await stdio_client.tools_list()
    last_fs_tool_names = {t.get("name", "") for t in fs_tools if isinstance(t, dict)}
    for t in fs_tools:
        tools.append({
            "name": "fs." + t.get("name", ""),
            "description": t.get("description", ""),
            "inputSchema": t.get("inputSchema", {}),
            "source": "fs",
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
                await handle_user_message(ws, session_id, content, file_uris)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("WebSocket error session=%s", session_id)

async def handle_user_message(ws: WebSocket, session_id: Optional[str], content: str, file_uris: List[str]) -> None:
    tools = await get_tools()
    status_payload = await resolve_status()
    await ws.send_text(json.dumps({"type": "status", **status_payload}))
    tool_names = {t.get("name", "") for t in tools}
    content_text = content or ""
    api_tools = [t for t in tools if t.get("source") == "api"]
    memory = session_conversations.get(session_id, []) if session_id else []
    state = session_state.get(session_id, {}) if session_id else {}

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

    delete_all = bool(re.search(r"\bdelete\b.*\bfiles?\b", content_text, re.IGNORECASE))
    ping_count = None
    file_base = "ping"
    name_fmt = None
    range_match = re.search(r"\b([a-z0-9_-]+)\((\d+)\s*-\s*(\d+)\)\.txt\b", content_text, re.IGNORECASE)
    if range_match:
        file_base = range_match.group(1)
        start = int(range_match.group(2))
        end = int(range_match.group(3))
        if end >= start:
            ping_count = end - start + 1
            name_fmt = f"{file_base}({{i}}).txt"
    times_match = re.search(r"\bping\b.*?(\d+)\s*times\b", content_text, re.IGNORECASE)
    if times_match:
        ping_count = int(times_match.group(1))
    if ping_count is not None and name_fmt is None:
        name_fmt = f"{file_base}{{i}}.txt"

    can_delete = delete_all and "fs.list_directory" in tool_names and "fs.delete_file" in tool_names
    can_ping = ping_count is not None and ping_count > 0 and "api.ping" in tool_names and "fs.write_file" in tool_names
    wants_all_api = bool(re.search(r"\b(all|every)\b.*\bapi\b.*\b(endpoints|tools)\b", content_text, re.IGNORECASE))
    wants_health = bool(re.search(r"\bhealth\b", content_text, re.IGNORECASE))
    wants_stats = bool(re.search(r"\bstats?\b", content_text, re.IGNORECASE))
    wants_widgets = bool(re.search(r"\bwidget\b", content_text, re.IGNORECASE))
    wants_repeat = bool(re.search(r"\b(same|as before|again|do it as before|do everything again)\b", content_text, re.IGNORECASE))
    wants_also = bool(re.search(r"\b(now\s+also|also)\b", content_text, re.IGNORECASE))
    wants_text_files = bool(
        re.search(r"\b(text\s+files?|files?)\b", content_text, re.IGNORECASE)
        or re.search(r"\.txt\b", content_text, re.IGNORECASE)
        or re.search(r"\bput\b.*\bfiles?\b", content_text, re.IGNORECASE)
    )
    if not wants_text_files and (wants_repeat or wants_also) and state.get("last_selected_tools"):
        wants_text_files = True
    can_write_files = "fs.write_file" in tool_names
    widget_tool_names = {"api.list_widgets", "api.get_widget", "api.search_widgets"}

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

    # Deterministic execution for delete + batch ping requests.
    if can_delete or can_ping:
        target_dir = default_fs_dir()
        explicit_dir = extract_target_dir(content_text)
        if explicit_dir and os.path.isdir(explicit_dir) and is_allowed_path(explicit_dir):
            target_dir = explicit_dir
        deleted_paths: List[str] = []
        if can_delete:
            list_result = await run_tool_ws("fs.list_directory", {"path": target_dir})
            for entry in extract_entries(list_result):
                entry_path = None
                entry_type = None
                if isinstance(entry, dict):
                    entry_type = entry.get("type") or entry.get("kind")
                    entry_path = entry.get("path")
                    if not entry_path and entry.get("name"):
                        entry_path = os.path.join(target_dir, str(entry.get("name")))
                elif isinstance(entry, str):
                    entry_path = os.path.join(target_dir, entry)
                if entry_type and str(entry_type).lower() == "directory":
                    continue
                if entry_path:
                    await run_tool_ws("fs.delete_file", {"path": entry_path})
                    deleted_paths.append(entry_path)
        written_paths: List[str] = []
        if can_ping:
            for i in range(1, ping_count + 1):
                result = await run_tool_ws("api.ping", {})
                content_value = result if isinstance(result, str) else json.dumps(result)
                filename = name_fmt.format(i=i) if name_fmt else f"{file_base}{i}.txt"
                file_path = os.path.join(target_dir, filename)
                await run_tool_ws("fs.write_file", {"path": file_path, "content": content_value})
                written_paths.append(file_path)
        summary_parts = []
        if can_delete:
            summary_parts.append(f"Deleted {len(deleted_paths)} file(s) from {target_dir}.")
        if can_ping:
            summary_parts.append(f"Wrote {len(written_paths)} ping response(s) to: " + ", ".join(written_paths))
        summary = " ".join(summary_parts) if summary_parts else "Done."
        await emit_assistant_message(ws, summary)
        if session_id is not None:
            session_conversations[session_id] = memory + [
                {"role": "user", "content": content_text},
                {"role": "assistant", "content": summary},
            ]
        return

    # Deterministic execution for all API tools or specific health/stats to files.
    if can_write_files and api_tools and (wants_all_api or ((wants_health or wants_stats or wants_widgets or wants_repeat or wants_also) and wants_text_files)):
        target_dir = default_fs_dir()
        explicit_dir = extract_target_dir(content_text)
        if explicit_dir and os.path.isdir(explicit_dir) and is_allowed_path(explicit_dir):
            target_dir = explicit_dir
        selected_tools: List[Dict[str, Any]] = []
        if wants_all_api:
            selected_tools = api_tools
        else:
            if wants_repeat and state.get("last_selected_tools"):
                selected_names = set(state.get("last_selected_tools", []))
                selected_tools.extend([t for t in api_tools if t.get("name") in selected_names])
            if wants_health:
                selected_tools.extend([t for t in api_tools if t.get("name") == "api.health_check"])
            if wants_stats:
                selected_tools.extend([t for t in api_tools if t.get("name") == "api.get_stats"])
            if wants_widgets:
                selected_tools.extend([t for t in api_tools if t.get("name") in widget_tool_names])
            if wants_also and wants_widgets and state.get("last_selected_tools"):
                selected_names = set(state.get("last_selected_tools", []))
                for t in api_tools:
                    if t.get("name") in selected_names and t not in selected_tools:
                        selected_tools.append(t)
        # Deduplicate while preserving order.
        seen_names: set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for t in selected_tools:
            name = t.get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                deduped.append(t)
        selected_tools = deduped
        written_paths: List[str] = []
        for tool in selected_tools:
            tool_name = tool.get("name", "")
            if not tool_name:
                continue
            args = default_args_for_tool(tool)
            result = await run_tool_ws(tool_name, args)
            content_value = summarize_result(result)
            base = tool_name.replace("api.", "")
            file_path = os.path.join(target_dir, f"{base}.txt")
            await run_tool_ws("fs.write_file", {"path": file_path, "content": content_value})
            written_paths.append(file_path)
        summary = "Wrote API outputs to: " + ", ".join(written_paths) if written_paths else "No API tools matched."
        await emit_assistant_message(ws, summary)
        if session_id is not None:
            state = session_state.get(session_id, {})
            state["last_selected_tools"] = [t.get("name") for t in selected_tools if t.get("name")]
            state["last_target_dir"] = target_dir
            session_state[session_id] = state
            session_conversations[session_id] = memory + [
                {"role": "user", "content": content_text},
                {"role": "assistant", "content": summary},
            ]
        return

    conversation: List[Dict[str, Any]] = list(memory)
    if content_text:
        conversation.append({"role": "user", "content": content_text})
    used_fs_write = False
    needs_file_write = bool(re.search(r"\b(save|write|store|put)\b", content_text, re.IGNORECASE)) and bool(
        re.search(r"\bfile\b|\\.txt\\b|\\.json\\b|\\.md\\b", content_text, re.IGNORECASE)
    )
    max_iters = 12
    for i in range(max_iters):
        decision = await gemini_client.decide(conversation, tools, "", file_uris)
        if decision.get("type") == "tool":
            name = decision.get("name", "")
            arguments = decision.get("arguments", {})
            call_id = str(uuid.uuid4())
            conversation.append({"role": "assistant", "content": json.dumps({"tool": name, "arguments": arguments})})
            await ws.send_text(json.dumps({"type": "tool_start", "callId": call_id, "name": name, "arguments": arguments}))
            try:
                result = await call_tool(name, arguments)
                await ws.send_text(json.dumps({"type": "tool_end", "callId": call_id, "result": result}))
                if name.startswith("fs.") and re.search(r"write|save", name, re.IGNORECASE):
                    used_fs_write = True
                conversation.append({"role": "tool", "name": name, "content": json.dumps(result)})
                content = ""
                continue
            except Exception as e:
                await ws.send_text(json.dumps({"type": "tool_error", "callId": call_id, "error": str(e)}))
                conversation.append({"role": "tool", "name": name, "content": str(e)})
                content = ""
                continue
        message = decision.get("message", "")
        if needs_file_write and not used_fs_write:
            if i < max_iters - 1:
                conversation.append({"role": "assistant", "content": message})
                conversation.append({
                    "role": "user",
                    "content": "You still need to write the result into a file using fs.* tools. Continue.",
                })
                continue
            # Last attempt: respond with a clear failure instead of hanging.
            await emit_assistant_message(
                ws,
                "I couldn't complete the file write within the tool budget. "
                "Please try again or specify the exact filename and directory.",
            )
            if session_id is not None:
                session_conversations[session_id] = conversation + [
                    {"role": "assistant", "content": "I couldn't complete the file write within the tool budget. Please try again or specify the exact filename and directory."},
                ]
            return
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
        if real_name == "delete_file" and real_name not in last_fs_tool_names:
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
    return {"error": "unknown_tool"}
