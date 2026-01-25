import os
import asyncio
from datetime import datetime
from typing import Any, Dict, List
from fastapi import UploadFile

class FileStore:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = os.path.abspath(base_dir)

    async def init(self) -> None:
        os.makedirs(self.base_dir, exist_ok=True)

    async def save_upload(self, file: UploadFile) -> Dict[str, Any]:
        await self.init()
        name = os.path.basename(file.filename or "file")
        dest_path = os.path.join(self.base_dir, name)
        if os.path.exists(dest_path):
            stem, ext = os.path.splitext(name)
            counter = 1
            while True:
                candidate = os.path.join(self.base_dir, f"{stem}_{counter}{ext}")
                if not os.path.exists(candidate):
                    dest_path = candidate
                    name = os.path.basename(dest_path)
                    break
                counter += 1
        size = 0
        with open(dest_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)
        created = datetime.utcnow().isoformat() + "Z"
        uri = "file://" + dest_path.replace("\\", "/")
        return {"id": name, "name": name, "size": size, "created": created, "uri": uri}

    async def list_files(self) -> List[Dict[str, Any]]:
        await self.init()
        entries: List[Dict[str, Any]] = []
        for name in os.listdir(self.base_dir):
            path = os.path.join(self.base_dir, name)
            if not os.path.isfile(path):
                continue
            stat = os.stat(path)
            created = datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z"
            uri = "file://" + path.replace("\\", "/")
            entries.append({
                "id": name,
                "name": name,
                "size": stat.st_size,
                "created": created,
                "uri": uri
            })
        entries.sort(key=lambda x: x["name"].lower())
        return entries

    async def delete_file(self, file_id: str) -> bool:
        await self.init()
        safe_name = os.path.basename(file_id)
        path = os.path.join(self.base_dir, safe_name)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except Exception:
                return False
        return False
