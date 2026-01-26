import os
import json
import asyncio
import re
from typing import Any, Dict, List
import httpx

class GeminiClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def decide(self, conversation: List[Dict[str, Any]], tools: List[Dict[str, Any]], user_message: str, file_uris: List[str]) -> Dict[str, Any]:
        if not self.api_key:
            return {"type": "final", "message": "Gemini API key is not configured"}
        system_prompt = self.build_system_prompt(tools, file_uris)
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": system_prompt}]},
                {"role": "user", "parts": [{"text": self.build_context(conversation, user_message)}]},
            ],
            "generationConfig": {"temperature": 0.2, "response_mime_type": "application/json"},
        }
        headers = {"Content-Type": "application/json"}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=25) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                text = self.extract_text(data)
                return self.parse_decision(text)
            except Exception:
                await asyncio.sleep(0.5 * (attempt + 1))
        return {"type": "final", "message": "Gemini request failed"}

    def build_system_prompt(self, tools: List[Dict[str, Any]], file_uris: List[str]) -> str:
        tools_json = json.dumps([{"name": t["name"], "description": t.get("description", ""), "inputSchema": t.get("inputSchema", {})} for t in tools])
        file_json = json.dumps(file_uris)
        allowed_dirs = [os.path.abspath(os.getenv("FILE_STORE_DIR", "./services/host-service/files"))]
        extra = os.getenv("FS_ALLOWED_DIRS", "")
        if extra:
            sep = ";" if os.name == "nt" else ":"
            for p in [p for p in extra.split(sep) if p]:
                allowed_dirs.append(os.path.abspath(p))
        allowed_json = json.dumps(allowed_dirs)
        return (
            "You are a tool-using agent for RapidMCP. Your job is to plan, use tools, verify results, and iterate until the task is fully done. "
            "You must use tools to read or change filesystem state and to call APIs. Never claim you deleted or wrote something unless a tool confirms it. "
            f"Allowed directories for fs tools: {allowed_json}. "
            "Only create, write, or delete files inside allowed directories and report the exact paths used. "
            "Use fs.* tools for reading, writing, listing, and managing files. "
            "Filesystem rules: "
            "If the user asks to list files, call fs.list_directory on the relevant path (never use fs.list_allowed_directories for listing files). "
            "If the user asks to delete files in a folder: first call fs.list_directory, then delete each listed file with fs.delete_file (or the appropriate delete tool), then call fs.list_directory again to verify. "
            "If the user provides an explicit list of file paths or names to delete, delete exactly those (no re-list required), then verify by listing the directory. "
            "If the user asks to write output to files, you must call an fs.* write tool for each file and then confirm the paths. "
            "Be professional and follow user instructions exactly. Do not rename files or change filenames unless explicitly requested. "
            "Do not repeat directory listings in the final message unless it is part of verification. "
            "API rules: use api.* tools for API operations. "
            "Iteration rule: you may need multiple tool calls, return one tool call per response and continue after receiving the tool result until the task is complete. "
            "Attached file URIs are provided. "
            "Output must be a single JSON object matching the decision schema. "
            "Decision schema: {\\\"type\\\":\\\"final\\\",\\\"message\\\":string} "
            "or {\\\"type\\\":\\\"tool\\\",\\\"name\\\":string,\\\"arguments\\\":object}. "
            f"Available tools: {tools_json}. "
            f"File URIs: {file_json}."
        )

    def build_context(self, conversation: List[Dict[str, Any]], user_message: str) -> str:
        messages = list(conversation)
        if user_message:
            messages.append({"role": "user", "content": user_message})
        return json.dumps(messages)

    def extract_text(self, data: Dict[str, Any]) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return ""
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        return "".join(texts)

    def parse_decision(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except Exception:
                pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return {"type": "final", "message": text}
