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
from urllib.parse import unquote

LOG_DIR = Path(__file__).resolve().parents[2] / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "host-service.log"
API_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "api_config.json"

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


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        try:
            return int(value)
        except Exception:
            return None
    return None


def _collect_keyed_ints(obj: Any, key: str) -> List[int]:
    out: List[int] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if key in node:
                iv = _safe_int(node.get(key))
                if iv is not None:
                    out.append(iv)
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)
    return out


def _extract_named_ids(obj: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            nid = _safe_int(node.get("id"))
            name = node.get("name")
            if nid is not None and isinstance(name, str) and name.strip():
                found.append({"id": nid, "name": name.strip()})
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)
    return found


def _update_asset_context(state: Dict[str, Any], tool_name: str, result: Any) -> Dict[str, Any]:
    if isinstance(result, dict) and "error" in result:
        return state

    ctx = state.get("assetContext")
    if not isinstance(ctx, dict):
        ctx = {}

    known_base_ids = [int(x) for x in ctx.get("knownBaseAssetIds", []) if isinstance(x, int)]
    known_rapid_ids = [int(x) for x in ctx.get("knownRapidModelIds", []) if isinstance(x, int)]
    known_preset_ids = [int(x) for x in ctx.get("knownPresetIds", []) if isinstance(x, int)]
    name_to_base = ctx.get("baseAssetNameToId", {})
    name_to_preset = ctx.get("presetNameToId", {})
    if not isinstance(name_to_base, dict):
        name_to_base = {}
    if not isinstance(name_to_preset, dict):
        name_to_preset = {}

    def push_unique(target: List[int], value: int, limit: int = 25) -> None:
        if value in target:
            target.remove(value)
        target.append(value)
        if len(target) > limit:
            del target[:-limit]

    rawmodel_ids = _collect_keyed_ints(result, "rawmodel_id")
    rapidmodel_ids = _collect_keyed_ints(result, "rapidmodel_id")

    tool_lc = (tool_name or "").lower()

    is_preset_tool = "preset" in tool_lc
    is_rapid_tool = "rapidmodel" in tool_lc
    is_base_tool = any(token in tool_lc for token in ("rawmodel", "base", "upload", "analysis"))
    is_optimize_tool = "optimize" in tool_lc

    for rid in rawmodel_ids:
        push_unique(known_base_ids, rid)
        ctx["lastBaseAssetId"] = rid

    for rid in rapidmodel_ids:
        push_unique(known_rapid_ids, rid)
        ctx["lastRapidModelId"] = rid

    direct_id = _safe_int(result.get("id")) if isinstance(result, dict) else None
    if direct_id is not None:
        if is_preset_tool:
            push_unique(known_preset_ids, direct_id)
            ctx["lastPresetId"] = direct_id
        elif is_rapid_tool or is_optimize_tool:
            push_unique(known_rapid_ids, direct_id)
            ctx["lastRapidModelId"] = direct_id
        elif is_base_tool:
            push_unique(known_base_ids, direct_id)
            ctx["lastBaseAssetId"] = direct_id

    for item in _extract_named_ids(result):
        item_id = int(item["id"])
        item_name = str(item["name"])
        normalized = item_name.lower()
        if is_preset_tool:
            push_unique(known_preset_ids, item_id)
            name_to_preset[normalized] = item_id
            ctx["lastPresetId"] = item_id
        elif is_rapid_tool:
            push_unique(known_rapid_ids, item_id)
        elif is_base_tool or is_optimize_tool:
            push_unique(known_base_ids, item_id)
            name_to_base[normalized] = item_id
            stem = Path(item_name).stem.lower()
            if stem:
                name_to_base[stem] = item_id
            ctx["lastBaseAssetId"] = item_id

    ctx["knownBaseAssetIds"] = known_base_ids
    ctx["knownRapidModelIds"] = known_rapid_ids
    ctx["knownPresetIds"] = known_preset_ids
    ctx["baseAssetNameToId"] = name_to_base
    ctx["presetNameToId"] = name_to_preset
    state["assetContext"] = ctx
    return state


def _strip_none_values(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            cleaned = _strip_none_values(v)
            if cleaned is not None:
                out[k] = cleaned
        return out
    if isinstance(value, list):
        out_list: List[Any] = []
        for item in value:
            cleaned = _strip_none_values(item)
            if cleaned is not None:
                out_list.append(cleaned)
        return out_list
    return value


def _extract_preset_id(arguments: Dict[str, Any]) -> Optional[int]:
    candidates: List[Any] = []
    if "preset_id" in arguments:
        candidates.append(arguments.get("preset_id"))
    body = arguments.get("body")
    if isinstance(body, dict) and "preset_id" in body:
        candidates.append(body.get("preset_id"))
    config = arguments.get("config")
    if isinstance(config, dict) and "preset_id" in config:
        candidates.append(config.get("preset_id"))
    for c in candidates:
        iv = _safe_int(c)
        if iv is not None and iv > 0:
            return iv
    return None


def _inject_preset_id(arguments: Dict[str, Any], preset_id: int) -> Dict[str, Any]:
    updated = dict(arguments)
    updated["preset_id"] = preset_id
    return updated


def _extract_config_obj(arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    config = arguments.get("config")
    if isinstance(config, dict):
        return config
    body = arguments.get("body")
    if isinstance(body, dict):
        body_config = body.get("config")
        if isinstance(body_config, dict):
            return body_config
    return None


def _is_likely_complete_optimize_config(config: Any) -> bool:
    # RapidPipeline rejects partial preset fragments (for example, only `limits`).
    # Require at least the known mandatory processor section.
    if not isinstance(config, dict) or not config:
        return False
    asset_simplification = config.get("assetSimplification")
    if not isinstance(asset_simplification, dict) or not asset_simplification:
        return False
    return True


def _normalize_optimize_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure optimize payload always conforms to the OpenAPI tool shape.
    normalized = dict(arguments)

    # `id` must remain untouched if present; model may provide it as string.
    model_id = _safe_int(normalized.get("id"))
    if model_id is not None:
        normalized["id"] = model_id

    # Keep only valid tags.
    tags = normalized.get("tags")
    if tags is not None:
        if isinstance(tags, list):
            normalized["tags"] = [str(t) for t in tags if isinstance(t, str) and t.strip()]
            if not normalized["tags"]:
                normalized.pop("tags", None)
        else:
            normalized.pop("tags", None)

    # Normalize `preset_id` and `config` to be mutually exclusive and valid.
    preset_id = _extract_preset_id(normalized)
    config = normalized.get("config")
    config_obj = config if isinstance(config, dict) and len(config) > 0 else None
    if config_obj is not None and not _is_likely_complete_optimize_config(config_obj):
        config_obj = None

    if preset_id is not None and preset_id > 0:
        normalized["preset_id"] = int(preset_id)
        normalized.pop("config", None)
    elif config_obj is not None:
        normalized["config"] = config_obj
        normalized.pop("preset_id", None)
    else:
        normalized.pop("preset_id", None)
        normalized.pop("config", None)

    # Drop any body wrapper if model produced one; optimize expects top-level fields.
    normalized.pop("body", None)
    return normalized


def _pick_known_preset_for_goal(asset_ctx: Dict[str, Any], user_text: str) -> Optional[int]:
    if not isinstance(asset_ctx, dict):
        return None
    name_to_preset = asset_ctx.get("presetNameToId", {})
    if not isinstance(name_to_preset, dict) or not name_to_preset:
        return None
    text = (user_text or "").lower()
    is_web = any(token in text for token in ("web", "website", "browser", "viewer"))
    is_mobile = any(token in text for token in ("mobile", "android", "ios", "fast", "small"))
    is_quality = any(token in text for token in ("high quality", "best quality", "hero", "cinematic"))

    scored: List[tuple[int, int]] = []
    for preset_name, pid_val in name_to_preset.items():
        pid = _safe_int(pid_val)
        if pid is None or pid <= 0:
            continue
        n = str(preset_name).lower()
        score = 0
        if is_web:
            if "webp" in n:
                score += 5
            if "web" in n:
                score += 4
            if "mid" in n:
                score += 3
            if "high" in n:
                score += 2
            if "low" in n:
                score += 1
        if is_mobile:
            if "low" in n:
                score += 3
            if "compression" in n:
                score += 3
            if "mid" in n:
                score += 1
        if is_quality:
            if "high" in n:
                score += 4
            if "quality" in n:
                score += 3
        if score > 0:
            scored.append((score, pid))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _pick_any_known_preset(asset_ctx: Dict[str, Any]) -> Optional[int]:
    if not isinstance(asset_ctx, dict):
        return None
    last_preset = asset_ctx.get("lastPresetId")
    if isinstance(last_preset, int) and last_preset > 0:
        return last_preset
    preset_ids = asset_ctx.get("knownPresetIds", [])
    if isinstance(preset_ids, list):
        for candidate in reversed(preset_ids):
            if isinstance(candidate, int) and candidate > 0:
                return candidate
    return None


def _extract_face_ratio_from_text(text: str) -> Optional[float]:
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.lower()
    if not any(token in t for token in ("face", "faces", "triangle", "triangles", "polygon", "polygons", "poly")):
        return None
    frac = re.search(r"\b(\d+)\s*/\s*(\d+)\b", t)
    if frac:
        num = int(frac.group(1))
        den = int(frac.group(2))
        if den > 0 and num > 0:
            ratio = float(num) / float(den)
            if 0 < ratio <= 1:
                return ratio
    pct = re.search(r"\b(\d{1,3})(?:\.\d+)?\s*%\b", t)
    if pct:
        p = int(pct.group(1))
        if 0 < p <= 100:
            return float(p) / 100.0
    if "half" in t:
        return 0.5
    if "third" in t:
        return 1.0 / 3.0
    if "quarter" in t:
        return 0.25
    return None


def _extract_preset_config_obj(result: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(result, dict):
        return None
    cfg = result.get("config")
    if isinstance(cfg, dict):
        return cfg
    if isinstance(cfg, str):
        try:
            parsed = json.loads(cfg)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    body = result.get("body")
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return _extract_preset_config_obj(parsed)
        except Exception:
            return None
    if isinstance(body, dict):
        return _extract_preset_config_obj(body)
    return None


def _apply_face_ratio_to_config(config: Dict[str, Any], ratio: float) -> Dict[str, Any]:
    updated = dict(config)
    limits = updated.get("limits")
    if not isinstance(limits, dict):
        limits = {}
    faces = limits.get("faces")
    if not isinstance(faces, dict):
        faces = {}
    percent = max(1, min(100, int(round(ratio * 100))))
    faces["percentage"] = percent
    faces.pop("count", None)
    limits["faces"] = faces
    updated["limits"] = limits
    return updated

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
    lowered_content = content_text.lower()
    has_batch_quantifier = bool(re.search(r"\b(all|every|each)\b", lowered_content))
    has_upload_intent = "upload" in lowered_content
    has_optimize_intent = any(token in lowered_content for token in ("optimize", "optimise", "optimization", "optimisation"))
    batch_guard_enabled = has_batch_quantifier and (has_upload_intent or has_optimize_intent)
    request_mentions_preset = bool(re.search(r"\bpreset\b", lowered_content))
    explicit_create_preset_intent = bool(
        re.search(r"\b(create|make|build|new)\b.*\bpreset\b", lowered_content)
        or re.search(r"\bpreset\b.*\b(create|make|build|new)\b", lowered_content)
    )
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

    def file_uri_to_path(uri: str) -> Optional[str]:
        if not isinstance(uri, str):
            return None
        text = uri.strip().strip("'\"")
        if not text.lower().startswith("file://"):
            return None
        raw = unquote(text[7:])
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
        raw = raw.replace("/", os.sep)
        try:
            return os.path.abspath(raw)
        except Exception:
            return None

    def resolve_local_path(value: str) -> str:
        raw = str(value or "").strip().strip("'\"")
        raw = raw.rstrip(" \t\r\n,;.!?)")
        if not raw:
            return raw

        from_uri = file_uri_to_path(raw)
        if isinstance(from_uri, str) and from_uri:
            return from_uri

        if os.path.isabs(raw):
            return os.path.abspath(raw)

        # If this is a plain filename, try selected file URIs first.
        basename = os.path.basename(raw).lower()
        uri_matches: List[str] = []
        for uri in file_uris:
            p = file_uri_to_path(uri)
            if not p:
                continue
            if os.path.basename(p).lower() == basename:
                uri_matches.append(p)
        if len(uri_matches) == 1:
            return uri_matches[0]

        # Relative paths are interpreted from the default allowed directory.
        default_candidate = os.path.abspath(os.path.join(default_fs_dir(), raw))
        if os.path.exists(default_candidate):
            return default_candidate

        # Try direct join in allowed dirs.
        direct_matches: List[str] = []
        for d in compute_allowed_dirs():
            candidate = os.path.abspath(os.path.join(d, raw))
            if os.path.exists(candidate):
                direct_matches.append(candidate)
        if len(direct_matches) == 1:
            return direct_matches[0]

        # Extension fallback for model files.
        if "." not in os.path.basename(raw):
            model_exts = [".glb", ".gltf", ".fbx", ".obj", ".stl", ".usdz", ".usd", ".zip"]
            for d in compute_allowed_dirs():
                for ext in model_exts:
                    candidate = os.path.abspath(os.path.join(d, raw + ext))
                    if os.path.exists(candidate):
                        return candidate

        # Case-insensitive filename match in allowed dirs.
        ci_matches: List[str] = []
        for d in compute_allowed_dirs():
            try:
                for entry in os.listdir(d):
                    if entry.lower() == basename:
                        ci_matches.append(os.path.abspath(os.path.join(d, entry)))
            except Exception:
                continue
        if len(ci_matches) == 1:
            return ci_matches[0]

        return raw

    def normalize_fs_arguments(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not name.startswith("fs.") or not isinstance(arguments, dict):
            return arguments
        updated = dict(arguments)
        for key in ("path", "filePath", "file_path", "uri"):
            val = updated.get(key)
            if isinstance(val, str) and val.strip():
                updated[key] = resolve_local_path(val)
        for key in ("paths", "filePaths", "file_paths", "uris"):
            val = updated.get(key)
            if isinstance(val, list):
                updated[key] = [resolve_local_path(v) if isinstance(v, str) else v for v in val]
        return updated

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
    optimized_count = 0
    uploaded_count = 0
    model_file_count_seen = 0
    batch_guard_nudges = 0
    request_locked_preset_id: Optional[int] = None
    optimized_base_ids: set[int] = set()
    uploaded_completed_stems: set[str] = set()
    pending_upload_stem: Optional[str] = None
    discovered_model_names: set[str] = set()
    uploaded_model_names: set[str] = set()

    furniture_keywords = {
        "bed",
        "chair",
        "table",
        "cupboard",
        "sofa",
        "desk",
        "shelf",
        "cabinet",
        "wardrobe",
        "dresser",
        "stool",
        "bench",
    }

    def is_model_filename(name: str) -> bool:
        if not isinstance(name, str):
            return False
        lowered = name.strip().lower()
        return lowered.endswith((".glb", ".gltf", ".fbx", ".obj", ".stl", ".usdz", ".usd", ".zip"))

    def count_model_files_from_entries(entries: List[Any]) -> int:
        count = 0
        for entry in entries:
            if isinstance(entry, str):
                if is_model_filename(entry):
                    count += 1
                continue
            if isinstance(entry, dict):
                name_val = entry.get("name") or entry.get("path") or entry.get("uri") or ""
                if isinstance(name_val, str) and is_model_filename(name_val):
                    count += 1
        return count

    def names_from_entries(entries: List[Any]) -> set[str]:
        out: set[str] = set()
        for entry in entries:
            name_val: Optional[str] = None
            if isinstance(entry, str):
                name_val = entry
            elif isinstance(entry, dict):
                raw = entry.get("name") or entry.get("path") or entry.get("uri")
                if isinstance(raw, str):
                    name_val = raw
            if not isinstance(name_val, str):
                continue
            base = os.path.basename(name_val.strip()).lower()
            stem, ext = os.path.splitext(base)
            if stem and ext in (".glb", ".gltf", ".fbx", ".obj", ".stl", ".usdz", ".usd", ".zip"):
                out.add(stem)
        return out

    def extract_model_stem_from_arguments(name: str, arguments: Dict[str, Any]) -> Optional[str]:
        if not isinstance(arguments, dict):
            return None
        if name == "http.put":
            file_path = arguments.get("filePath")
            if isinstance(file_path, str) and file_path.strip():
                base = os.path.basename(file_path.strip()).lower()
                stem, ext = os.path.splitext(base)
                if stem and ext in (".glb", ".gltf", ".fbx", ".obj", ".stl", ".usdz", ".usd", ".zip"):
                    return stem
        filename = arguments.get("filename")
        if isinstance(filename, str) and filename.strip():
            base = os.path.basename(filename.strip()).lower()
            stem, ext = os.path.splitext(base)
            if stem and ext in (".glb", ".gltf", ".fbx", ".obj", ".stl", ".usdz", ".usd", ".zip"):
                return stem
        return None

    def infer_expected_batch_targets() -> set[str]:
        if not discovered_model_names:
            return set()
        if "furniture" in lowered_content:
            return {name for name in discovered_model_names if any(token in name for token in furniture_keywords)}
        if re.search(r"\ball\b.*\bmodels?\b", lowered_content):
            return set(discovered_model_names)
        return set()

    def extract_base_asset_id(value: Any) -> Optional[int]:
        if isinstance(value, dict):
            direct = _safe_int(value.get("rawmodel_id"))
            if isinstance(direct, int) and direct > 0:
                return direct
            alt = _safe_int(value.get("id"))
            if isinstance(alt, int) and alt > 0:
                return alt
        return None
    while True:
        asset_ctx = state.get("assetContext", {}) if isinstance(state, dict) else {}
        if not isinstance(asset_ctx, dict):
            asset_ctx = {}
        hint_payload: Dict[str, Any] = {}
        if isinstance(asset_ctx.get("lastBaseAssetId"), int):
            hint_payload["lastBaseAssetId"] = asset_ctx.get("lastBaseAssetId")
        if isinstance(asset_ctx.get("lastRapidModelId"), int):
            hint_payload["lastRapidModelId"] = asset_ctx.get("lastRapidModelId")
        if isinstance(asset_ctx.get("lastPresetId"), int):
            hint_payload["lastPresetId"] = asset_ctx.get("lastPresetId")
        base_ids = asset_ctx.get("knownBaseAssetIds", [])
        rapid_ids = asset_ctx.get("knownRapidModelIds", [])
        preset_ids = asset_ctx.get("knownPresetIds", [])
        if isinstance(base_ids, list) and base_ids:
            hint_payload["knownBaseAssetIds"] = base_ids[-10:]
        if isinstance(rapid_ids, list) and rapid_ids:
            hint_payload["knownRapidModelIds"] = rapid_ids[-10:]
        if isinstance(preset_ids, list) and preset_ids:
            hint_payload["knownPresetIds"] = preset_ids[-10:]
        named_map = asset_ctx.get("baseAssetNameToId", {})
        if isinstance(named_map, dict) and named_map:
            trimmed_map = dict(list(named_map.items())[-20:])
            hint_payload["baseAssetNameToId"] = trimmed_map
        preset_map = asset_ctx.get("presetNameToId", {})
        if isinstance(preset_map, dict) and preset_map:
            trimmed_preset_map = dict(list(preset_map.items())[-20:])
            hint_payload["presetNameToId"] = trimmed_preset_map
        hint_text = ""
        if hint_payload:
            hint_text = (
                "Session asset context (source of truth; never guess IDs): "
                + json.dumps(hint_payload)
            )

        decision = await gemini_client.decide(
            conversation,
            tools,
            hint_text,
            file_uris,
            config_override=normalized_override,
        )
        decision_type = decision.get("type")
        if decision_type not in ("tool", "final"):
            logger.warning("Model returned invalid decision type: %s", decision)
            decision_keys = sorted(decision.keys()) if isinstance(decision, dict) else []
            message = (
                "I couldn't continue because the model returned an invalid decision format "
                f"(type={repr(decision_type)}, keys={decision_keys}). Please try again."
            )
            message = await emit_assistant_message(ws, message)
            if session_id is not None:
                session_conversations[session_id] = conversation + [{"role": "assistant", "content": message}]
            return
        if decision_type == "tool":
            name = decision.get("name", "")
            if not isinstance(name, str) or not name:
                logger.warning("Model returned tool call without name: %s", decision)
                message = "Model returned an invalid tool call. Please try again."
                message = await emit_assistant_message(ws, message)
                if session_id is not None:
                    session_conversations[session_id] = conversation + [{"role": "assistant", "content": message}]
                return
            lower_tool_name = name.lower()
            if (
                request_mentions_preset
                and not explicit_create_preset_intent
                and lower_tool_name.startswith("api.")
                and "preset" in lower_tool_name
                and "create" in lower_tool_name
            ):
                guard_error = {
                    "error": "preset_creation_not_requested",
                    "tool": name,
                    "message": (
                        "Do not create a new preset for this request. "
                        "Use existing preset discovery/selection tools and continue."
                    ),
                }
                conversation.append({"role": "tool", "name": name, "content": json.dumps(guard_error)})
                last_tool_result = guard_error
                last_tool_name = name
                continue
            raw_arguments = decision.get("arguments", {})
            arguments = _strip_none_values(raw_arguments) if isinstance(raw_arguments, dict) else {}
            arguments = normalize_fs_arguments(name, arguments)
            if batch_guard_enabled and name == "http.put":
                put_stem = extract_model_stem_from_arguments(name, arguments)
                if isinstance(put_stem, str) and put_stem in uploaded_completed_stems:
                    skipped = {"skipped": True, "reason": "already_uploaded_in_request", "model": put_stem}
                    last_tool_result = skipped
                    last_tool_name = name
                    conversation.append({"role": "tool", "name": name, "content": json.dumps(skipped)})
                    continue
                pending_upload_stem = put_stem or pending_upload_stem
            if name == "api.optimize":
                target_face_ratio = _extract_face_ratio_from_text(content_text)
                raw_config_obj = _extract_config_obj(arguments)
                had_incomplete_config = (
                    isinstance(raw_config_obj, dict)
                    and len(raw_config_obj) > 0
                    and not _is_likely_complete_optimize_config(raw_config_obj)
                )
                arguments = _normalize_optimize_arguments(arguments)
                preset_id = _extract_preset_id(arguments)
                config_obj = _extract_config_obj(arguments)
                if preset_id is None:
                    last_preset = asset_ctx.get("lastPresetId") if isinstance(asset_ctx, dict) else None
                    if isinstance(last_preset, int) and last_preset > 0:
                        arguments = _inject_preset_id(arguments, last_preset)
                        preset_id = last_preset
                if preset_id is None and isinstance(asset_ctx, dict):
                    inferred_preset = _pick_known_preset_for_goal(asset_ctx, content_text)
                    if isinstance(inferred_preset, int) and inferred_preset > 0:
                        arguments = _inject_preset_id(arguments, inferred_preset)
                        preset_id = inferred_preset
                # Request-level consistency: once a preset is selected for this request,
                # keep using it for all remaining optimize calls in the same request.
                if isinstance(request_locked_preset_id, int) and request_locked_preset_id > 0:
                    arguments = _inject_preset_id(arguments, request_locked_preset_id)
                    preset_id = request_locked_preset_id
                # Re-normalize after any preset injection.
                arguments = _normalize_optimize_arguments(arguments)
                config_obj = _extract_config_obj(arguments)
                if preset_id is None and not (isinstance(config_obj, dict) and len(config_obj) > 0):
                    # Auto-discover presets so optimization can proceed even if the model
                    # did not explicitly call preset discovery tools first.
                    for preset_tool in ("api.getFactoryPresets", "api.getCustomPresets"):
                        try:
                            preset_result = await call_tool(preset_tool, {})
                            last_tool_result = preset_result
                            last_tool_name = preset_tool
                            state = _update_asset_context(state, preset_tool, preset_result)
                            if session_id is not None:
                                session_state[session_id] = state
                            conversation.append({"role": "tool", "name": preset_tool, "content": json.dumps(preset_result)})
                            asset_ctx = state.get("assetContext", {}) if isinstance(state, dict) else {}
                            discovered = _pick_known_preset_for_goal(asset_ctx, content_text)
                            if discovered is None:
                                discovered = _pick_any_known_preset(asset_ctx)
                            if isinstance(discovered, int) and discovered > 0:
                                arguments = _inject_preset_id(arguments, discovered)
                                preset_id = discovered
                                break
                        except Exception as preset_discovery_error:
                            conversation.append(
                                {
                                    "role": "tool",
                                    "name": preset_tool,
                                    "content": json.dumps({"error": str(preset_discovery_error)}),
                                }
                            )
                            continue
                    arguments = _normalize_optimize_arguments(arguments)
                    config_obj = _extract_config_obj(arguments)
                # If user requested relative face reduction, prefer a concrete config
                # derived from a real preset so optimize can honor the ratio precisely.
                if isinstance(target_face_ratio, float) and 0 < target_face_ratio <= 1:
                    ratio_config: Optional[Dict[str, Any]] = None
                    if isinstance(config_obj, dict) and _is_likely_complete_optimize_config(config_obj):
                        ratio_config = _apply_face_ratio_to_config(config_obj, target_face_ratio)
                    elif isinstance(preset_id, int) and preset_id > 0:
                        try:
                            preset_details = await call_tool("api.getPreset", {"id": preset_id})
                            last_tool_result = preset_details
                            last_tool_name = "api.getPreset"
                            state = _update_asset_context(state, "api.getPreset", preset_details)
                            if session_id is not None:
                                session_state[session_id] = state
                            conversation.append({"role": "tool", "name": "api.getPreset", "content": json.dumps(preset_details)})
                            preset_cfg = _extract_preset_config_obj(preset_details)
                            if isinstance(preset_cfg, dict) and _is_likely_complete_optimize_config(preset_cfg):
                                ratio_config = _apply_face_ratio_to_config(preset_cfg, target_face_ratio)
                        except Exception as preset_get_error:
                            conversation.append(
                                {
                                    "role": "tool",
                                    "name": "api.getPreset",
                                    "content": json.dumps({"error": str(preset_get_error)}),
                                }
                            )
                    if isinstance(ratio_config, dict):
                        arguments["config"] = ratio_config
                        arguments.pop("preset_id", None)
                        arguments = _normalize_optimize_arguments(arguments)
                        preset_id = _extract_preset_id(arguments)
                        config_obj = _extract_config_obj(arguments)
                if preset_id is None and had_incomplete_config and not (isinstance(config_obj, dict) and len(config_obj) > 0):
                    guard_error = {
                        "error": "invalid_optimize_arguments",
                        "tool": "api.optimize",
                        "message": (
                            "Incomplete optimize config. Do not send partial preset fragments "
                            "(e.g. limits-only). Call a preset api.* tool and retry optimize "
                            "with preset_id, or provide a full preset-compatible config."
                        ),
                    }
                    conversation.append({"role": "tool", "name": "api.optimize", "content": json.dumps(guard_error)})
                    last_tool_result = guard_error
                    last_tool_name = "api.optimize"
                    continue
                # Guard: never call optimize without either a valid preset_id or a config object.
                if preset_id is None and not (isinstance(config_obj, dict) and len(config_obj) > 0):
                    guard_error = {
                        "error": "invalid_optimize_arguments",
                        "tool": "api.optimize",
                        "message": "Optimize requires either a valid preset_id or a non-empty config object.",
                    }
                    conversation.append({"role": "tool", "name": "api.optimize", "content": json.dumps(guard_error)})
                    last_tool_result = guard_error
                    last_tool_name = "api.optimize"
                    continue
                if preset_id is not None and isinstance(state, dict):
                    state_ctx = state.get("assetContext")
                    if not isinstance(state_ctx, dict):
                        state_ctx = {}
                    state_ctx["lastPresetId"] = preset_id
                    known = state_ctx.get("knownPresetIds", [])
                    if not isinstance(known, list):
                        known = []
                    if preset_id not in known:
                        known.append(preset_id)
                    state_ctx["knownPresetIds"] = known[-25:]
                    state["assetContext"] = state_ctx
                    if session_id is not None:
                        session_state[session_id] = state
                if batch_guard_enabled:
                    optimize_target_id = _safe_int(arguments.get("id"))
                    if isinstance(optimize_target_id, int) and optimize_target_id in optimized_base_ids:
                        skipped = {
                            "skipped": True,
                            "reason": "already_optimized_in_request",
                            "id": optimize_target_id,
                        }
                        last_tool_result = skipped
                        last_tool_name = name
                        conversation.append({"role": "tool", "name": name, "content": json.dumps(skipped)})
                        continue
            call_id = str(uuid.uuid4())
            conversation.append({"role": "assistant", "content": json.dumps({"tool": name, "arguments": arguments})})
            await ws.send_text(json.dumps({"type": "tool_start", "callId": call_id, "name": name, "arguments": arguments}))
            try:
                result = await call_tool(name, arguments)
                await ws.send_text(json.dumps({"type": "tool_end", "callId": call_id, "result": result}))
                uploaded_stem = extract_model_stem_from_arguments(name, arguments)
                if uploaded_stem:
                    uploaded_model_names.add(uploaded_stem)
                if name == "fs.list_directory":
                    entries = extract_entries(result)
                    if isinstance(entries, list):
                        model_file_count_seen = max(model_file_count_seen, count_model_files_from_entries(entries))
                        discovered_model_names.update(names_from_entries(entries))
                if name == "api.createBaseAssetCompleteUpload":
                    completed_stem = pending_upload_stem or extract_model_stem_from_arguments(name, arguments)
                    if completed_stem and completed_stem not in uploaded_completed_stems:
                        uploaded_completed_stems.add(completed_stem)
                        uploaded_count += 1
                    elif not completed_stem:
                        uploaded_count += 1
                    pending_upload_stem = None
                if name == "api.optimize":
                    optimize_target_id = _safe_int(arguments.get("id"))
                    if isinstance(optimize_target_id, int):
                        if optimize_target_id not in optimized_base_ids:
                            optimized_base_ids.add(optimize_target_id)
                            optimized_count += 1
                    else:
                        optimized_count += 1
                    if (
                        isinstance(preset_id, int)
                        and preset_id > 0
                        and (batch_guard_enabled or request_mentions_preset)
                        and request_locked_preset_id is None
                        and not (isinstance(result, dict) and "error" in result)
                    ):
                        request_locked_preset_id = preset_id
                if name.startswith("fs.") and re.search(r"write|save", name, re.IGNORECASE):
                    used_fs_write = True
                last_tool_result = result
                last_tool_name = name
                state = _update_asset_context(state, name, result)
                if session_id is not None:
                    session_state[session_id] = state
                conversation.append({"role": "tool", "name": name, "content": json.dumps(result)})
                if not gemini_client.is_configured(normalized_override):
                    summary = summarize_result(result)
                    message = f"Done. {summary}"
                    message = await emit_assistant_message(ws, message)
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
        if batch_guard_enabled:
            has_multiple_models = model_file_count_seen > 1
            expected_targets = infer_expected_batch_targets()
            has_only_partial_progress = (
                (has_optimize_intent and optimized_count <= 1)
                or (has_upload_intent and uploaded_count <= 1)
            )
            has_missing_named_targets = bool(expected_targets) and len(uploaded_model_names.intersection(expected_targets)) < len(expected_targets)
            has_optimize_lag = has_optimize_intent and optimized_count < max(1, len(uploaded_model_names))
            should_continue = (has_multiple_models and has_only_partial_progress) or has_missing_named_targets or has_optimize_lag
            if should_continue and batch_guard_nudges < 6:
                batch_guard_nudges += 1
                conversation.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue executing the same request for all remaining matching items. "
                            "Do not finalize yet; keep calling tools until batch processing is complete."
                        ),
                    }
                )
                continue

        message = decision.get("message", "")
        if not isinstance(message, str) or not message.strip():
            logger.warning("Model returned empty message: %s", decision)
            message = "Model returned an empty response. Please try again."
        message = await emit_assistant_message(ws, message)
        if session_id is not None:
            session_conversations[session_id] = conversation + [{"role": "assistant", "content": message}]
        return

def sanitize_assistant_message(message: str) -> str:
    if not isinstance(message, str) or not message:
        return ""

    # Remove markdown links and raw URLs that point to image/QC render resources.
    md_image_link_re = re.compile(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        re.IGNORECASE,
    )
    raw_url_re = re.compile(r"https?://\S+", re.IGNORECASE)
    image_hint_re = re.compile(
        r"(qcrenders|/qc(?:_|-)renders/|\.(png|jpg|jpeg|webp|gif)(\?|$))",
        re.IGNORECASE,
    )

    removed = False

    def replace_md_link(match: re.Match[str]) -> str:
        nonlocal removed
        label = match.group(1) or "image"
        url = match.group(2) or ""
        if image_hint_re.search(url):
            removed = True
            return f"{label} (image URL omitted)"
        return match.group(0)

    text = md_image_link_re.sub(replace_md_link, message)

    def replace_raw_url(match: re.Match[str]) -> str:
        nonlocal removed
        url = match.group(0) or ""
        if image_hint_re.search(url):
            removed = True
            return "[image URL omitted]"
        return url

    text = raw_url_re.sub(replace_raw_url, text)

    # If the message was mostly URL dumps, provide a concise fallback.
    if removed:
        stripped = re.sub(r"[ \t]+", " ", text).strip()
        if not stripped or stripped in {"[image URL omitted]", "- [image URL omitted]"}:
            return "Optimization was queued. Image URLs are omitted."
    return text

async def emit_assistant_message(ws: WebSocket, message: str) -> str:
    message = sanitize_assistant_message(message)
    chunk_size = 40
    for i in range(0, len(message), chunk_size):
        delta = message[i:i+chunk_size]
        await ws.send_text(json.dumps({"type": "assistant_delta", "content": delta}))
        await asyncio.sleep(0.01)
    await ws.send_text(json.dumps({"type": "assistant_message", "content": message}))
    return message

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
