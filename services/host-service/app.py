import os
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
    global cached_tools, last_tools_refresh
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
    for t in fs_tools:
        tools.append({
            "name": "fs." + t.get("name", ""),
            "description": t.get("description", ""),
            "inputSchema": t.get("inputSchema", {}),
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
                status_payload = await resolve_status()
                await ws.send_text(json.dumps({"type": "status", **status_payload}))
            elif msg_type == "user_message":
                session_id = data.get("sessionId")
                content = data.get("content", "")
                file_uris = data.get("fileUris", [])
                await handle_user_message(ws, content, file_uris)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("WebSocket error session=%s", session_id)

async def handle_user_message(ws: WebSocket, content: str, file_uris: List[str]) -> None:
    tools = await get_tools()
    status_payload = await resolve_status()
    await ws.send_text(json.dumps({"type": "status", **status_payload}))
    conversation: List[Dict[str, Any]] = []
    for _ in range(8):
        decision = await gemini_client.decide(conversation, tools, content, file_uris)
        if decision.get("type") == "tool":
            name = decision.get("name", "")
            arguments = decision.get("arguments", {})
            call_id = str(uuid.uuid4())
            await ws.send_text(json.dumps({"type": "tool_start", "callId": call_id, "name": name, "arguments": arguments}))
            try:
                result = await call_tool(name, arguments)
                await ws.send_text(json.dumps({"type": "tool_end", "callId": call_id, "result": result}))
                conversation.append({"role": "tool", "name": name, "content": json.dumps(result)})
                content = ""
                continue
            except Exception as e:
                await ws.send_text(json.dumps({"type": "tool_error", "callId": call_id, "error": str(e)}))
                conversation.append({"role": "tool", "name": name, "content": str(e)})
                content = ""
                continue
        message = decision.get("message", "")
        await emit_assistant_message(ws, message)
        return

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
        return await stdio_client.tools_call(real_name, arguments)
    if name.startswith("api."):
        real_name = name[len("api."):]
        return await mcp_http.tools_call(real_name, arguments)
    return {"error": "unknown_tool"}
