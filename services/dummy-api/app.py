from __future__ import annotations

from fastapi import FastAPI, HTTPException
from typing import Dict, List
import time

app = FastAPI(title="Dummy Widgets API")

# Simple in-memory data for testing
WIDGETS: List[Dict[str, object]] = [
    {"id": "w-100", "name": "Gizmo", "category": "tools", "price": 12.5},
    {"id": "w-101", "name": "Sprocket", "category": "parts", "price": 3.75},
    {"id": "w-102", "name": "Fluxer", "category": "tools", "price": 99.0},
]

@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}

@app.get("/widgets")
async def list_widgets(limit: int = 10, category: str | None = None) -> Dict[str, object]:
    items = WIDGETS
    if category:
        items = [w for w in items if w.get("category") == category]
    return {"items": items[: max(0, min(limit, 100))], "count": len(items)}

@app.get("/widgets/{widget_id}")
async def get_widget(widget_id: str) -> Dict[str, object]:
    for w in WIDGETS:
        if w.get("id") == widget_id:
            return w
    raise HTTPException(status_code=404, detail="Widget not found")

@app.get("/search")
async def search_widgets(q: str) -> Dict[str, object]:
    q_lower = q.lower().strip()
    results = [w for w in WIDGETS if q_lower in str(w.get("name", "")).lower()]
    return {"items": results, "query": q, "count": len(results)}

@app.get("/stats")
async def get_stats() -> Dict[str, object]:
    return {
        "widgets": len(WIDGETS),
        "categories": sorted({w.get("category") for w in WIDGETS}),
        "serverTime": int(time.time()),
    }
