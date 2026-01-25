import os
import json
import asyncio
import subprocess
import logging
from typing import Any, Dict, List, Optional

class StdioMcpClient:
    def __init__(self, file_store_dir: str) -> None:
        self.file_store_dir = os.path.abspath(file_store_dir)
        self.process: Optional[subprocess.Popen] = None
        self.pending: Dict[int, asyncio.Future] = {}
        self.reader_task: Optional[asyncio.Task] = None
        self.stderr_task: Optional[asyncio.Task] = None
        self.is_running = False
        self._id = 1
        self.logger = logging.getLogger("host-service.fs-mcp")

    async def start(self) -> None:
        if self.is_running:
            return
        cmd = os.getenv("FS_NPX_COMMAND", "npx")
        pkg = os.getenv("FS_MCP_PACKAGE", "@modelcontextprotocol/server-filesystem")
        allowed_dirs = self._compute_allowed_dirs()
        args = ["-y", pkg] + allowed_dirs
        self.logger.info("Starting fs MCP: %s %s", cmd, " ".join(args))
        try:
            self.process = subprocess.Popen(
                [cmd] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception:
            if os.name == "nt" and cmd == "npx":
                try:
                    self.logger.warning("npx launch failed, retrying with npx.cmd")
                    self.process = subprocess.Popen(
                        ["npx.cmd"] + args,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                    )
                except Exception:
                    self.logger.exception("Failed to start fs MCP via npx.cmd")
                    self.is_running = False
                    return
            else:
                self.logger.exception("Failed to start fs MCP")
                self.is_running = False
                self.logger.warning("fs MCP stdout closed")
                return
        self.is_running = True
        self.reader_task = asyncio.create_task(self._reader_loop())
        if self.process and self.process.stderr:
            self.stderr_task = asyncio.create_task(self._stderr_loop())

    async def stop(self) -> None:
        if not self.is_running:
            return
        if self.process:
            self.process.kill()
        self.is_running = False
        if self.reader_task:
            self.reader_task.cancel()
        if self.stderr_task:
            self.stderr_task.cancel()

    def _compute_allowed_dirs(self) -> List[str]:
        dirs = [self.file_store_dir]
        extra = os.getenv("FS_ALLOWED_DIRS", "")
        if extra:
            sep = ";" if os.name == "nt" else ":"
            parts = [os.path.abspath(p) for p in extra.split(sep) if p]
            dirs.extend(parts)
        return dirs

    async def _reader_loop(self) -> None:
        if not self.process or not self.process.stdout:
            return
        while True:
            line = await asyncio.to_thread(self.process.stdout.readline)
            if not line:
                self.is_running = False
                self.logger.warning("fs MCP stdout closed")
                return
            try:
                data = json.loads(line)
            except Exception:
                continue
            if "id" in data and data["id"] in self.pending:
                fut = self.pending.pop(data["id"])
                if not fut.done():
                    fut.set_result(data)

    async def _stderr_loop(self) -> None:
        if not self.process or not self.process.stderr:
            return
        while True:
            line = await asyncio.to_thread(self.process.stderr.readline)
            if not line:
                return
            self.logger.warning("fs MCP stderr: %s", line.rstrip())

    async def _send(self, method: str, params: Dict[str, Any]) -> Any:
        if not self.is_running or not self.process or not self.process.stdin:
            raise RuntimeError("fs_mcp_not_running")
        req_id = self._id
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        fut = asyncio.get_event_loop().create_future()
        self.pending[req_id] = fut
        data = json.dumps(payload)
        await asyncio.to_thread(self.process.stdin.write, data + "\n")
        await asyncio.to_thread(self.process.stdin.flush)
        try:
            resp = await asyncio.wait_for(fut, timeout=20)
        except Exception:
            self.pending.pop(req_id, None)
            raise
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp.get("result")

    async def tools_list(self) -> List[Dict[str, Any]]:
        result = await self._send("tools/list", {})
        return result.get("tools", [])

    async def tools_call(self, name: str, arguments: Dict[str, Any]) -> Any:
        result = await self._send("tools/call", {"name": name, "arguments": arguments})
        return result
