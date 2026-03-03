import os
import json
import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List
import httpx

class GeminiClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.context_window = int(os.getenv("AGENT_CONTEXT_WINDOW_SIZE", "6000"))
        self.preprompt_path = Path(os.getenv("PREPROMPT_PATH", Path(__file__).with_name("preprompt.json")))
        self.config_path = Path(os.getenv("API_CONFIG_PATH", Path(__file__).resolve().parents[2] / "config" / "api_config.json"))

    def _load_runtime_config(self) -> Dict[str, str]:
        if not self.config_path.exists():
            return {"geminiApiKey": "", "geminiModel": ""}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                return {"geminiApiKey": "", "geminiModel": ""}
            return {
                "geminiApiKey": str(data.get("geminiApiKey") or ""),
                "geminiModel": str(data.get("geminiModel") or ""),
            }
        except Exception:
            return {"geminiApiKey": "", "geminiModel": ""}

    def is_configured(self, override: Dict[str, str] | None = None) -> bool:
        if override and override.get("geminiApiKey"):
            return True
        cfg = self._load_runtime_config()
        return bool(cfg.get("geminiApiKey") or self.api_key)

    def current_model(self, override: Dict[str, str] | None = None) -> str:
        if override and override.get("geminiModel"):
            return override.get("geminiModel") or self.model_name
        cfg = self._load_runtime_config()
        return cfg.get("geminiModel") or self.model_name

    async def decide(
        self,
        conversation: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        internal_hint: str,
        file_uris: List[str],
        config_override: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        cfg = self._load_runtime_config()
        api_key = (config_override or {}).get("geminiApiKey") or cfg.get("geminiApiKey") or self.api_key
        model_name = (config_override or {}).get("geminiModel") or cfg.get("geminiModel") or self.model_name
        if not api_key:
            return {"type": "final", "message": "Gemini API key is not configured"}
        system_prompt = self.build_system_prompt(tools, file_uris, internal_hint)
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": system_prompt}]},
                {"role": "user", "parts": [{"text": self.build_context(conversation)}]},
            ],
            "generationConfig": {"temperature": 0.2, "response_mime_type": "application/json"},
        }
        headers = {"Content-Type": "application/json"}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
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

    def build_system_prompt(self, tools: List[Dict[str, Any]], file_uris: List[str], internal_hint: str = "") -> str:
        tools_json = json.dumps([{"name": t["name"], "description": t.get("description", ""), "inputSchema": t.get("inputSchema", {})} for t in tools])
        file_json = json.dumps(file_uris)
        allowed_dirs = [os.path.abspath(os.getenv("FILE_STORE_DIR", "./services/host-service/files"))]
        extra = os.getenv("FS_ALLOWED_DIRS", "")
        if extra:
            sep = ";" if os.name == "nt" else ":"
            for p in [p for p in extra.split(sep) if p]:
                allowed_dirs.append(os.path.abspath(p))
        allowed_json = json.dumps(allowed_dirs)

        template = self._load_preprompt_template()
        if not template:
            return (
                "You are a tool-using agent for RapidMCP. "
                f"Available tools: {tools_json}. "
                f"File URIs: {file_json}. "
                f"Allowed directories for fs tools: {allowed_json}. "
                f"Context window size (characters): {self.context_window}."
            )

        variables = {
            "{{tools_json}}": tools_json,
            "{{file_json}}": file_json,
            "{{allowed_dirs}}": allowed_json,
            "{{context_window}}": str(self.context_window),
        }
        rendered = self._render_template(template, variables)
        if internal_hint:
            rendered += (
                "\n\n## Internal Session Context\n"
                "Use the following context to improve tool selection and ID resolution. "
                "Do not repeat this context verbatim to the user unless explicitly asked.\n"
                f"{internal_hint}"
            )
        return rendered

    def _load_preprompt_template(self) -> Dict[str, Any]:
        try:
            if self.preprompt_path.exists():
                return json.loads(self.preprompt_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {}

    def _render_template(self, template: Dict[str, Any], variables: Dict[str, str]) -> str:
        header = template.get("header", "").strip()
        sections = template.get("sections", [])
        blocks: List[str] = []
        if header:
            blocks.append(header)
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                title = str(section.get("title", "")).strip()
                lines = section.get("lines", [])
                if title:
                    blocks.append(f"\n## {title}")
                if isinstance(lines, list):
                    for line in lines:
                        if not isinstance(line, str):
                            continue
                        blocks.append(line)
        text = "\n".join(blocks)
        for key, value in variables.items():
            text = text.replace(key, value)
        return text

    def build_context(self, conversation: List[Dict[str, Any]]) -> str:
        messages = list(conversation)
        if self.context_window <= 0:
            return json.dumps(messages)
        while len(messages) > 1:
            serialized = json.dumps(messages)
            if len(serialized) <= self.context_window:
                return serialized
            messages.pop(0)
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
                data = json.loads(text)
                if isinstance(data, dict):
                    if data.get("type") in ("tool", "final"):
                        return data
                    if "tool" in data and isinstance(data.get("tool"), str):
                        return {"type": "tool", "name": data.get("tool"), "arguments": data.get("arguments") or {}}
                    if "name" in data and "arguments" in data and isinstance(data.get("name"), str):
                        return {"type": "tool", "name": data.get("name"), "arguments": data.get("arguments") or {}}
                    if "message" in data and isinstance(data.get("message"), str):
                        return {"type": "final", "message": data.get("message")}
                return {"type": "final", "message": json.dumps(data)}
            except Exception:
                pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    if data.get("type") in ("tool", "final"):
                        return data
                    if "tool" in data and isinstance(data.get("tool"), str):
                        return {"type": "tool", "name": data.get("tool"), "arguments": data.get("arguments") or {}}
                    if "name" in data and "arguments" in data and isinstance(data.get("name"), str):
                        return {"type": "tool", "name": data.get("name"), "arguments": data.get("arguments") or {}}
                    if "message" in data and isinstance(data.get("message"), str):
                        return {"type": "final", "message": data.get("message")}
                return {"type": "final", "message": json.dumps(data)}
            except Exception:
                pass
        return {"type": "final", "message": text}
