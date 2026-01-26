from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="Dummy Widgets API", version="1.0.0")

WIDGETS: List[Dict[str, str]] = [
    {"id": "w1", "name": "Alpha Widget", "category": "alpha"},
    {"id": "w2", "name": "Beta Widget", "category": "beta"},
    {"id": "w3", "name": "Gamma Widget", "category": "gamma"},
    {"id": "w4", "name": "Delta Widget", "category": "alpha"},
    {"id": "w5", "name": "Epsilon Widget", "category": "beta"},
]


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/widgets")
async def list_widgets(
    limit: int = Query(10, ge=1),
    category: Optional[str] = Query(None),
) -> Dict[str, List[Dict[str, str]]]:
    items = WIDGETS
    if category:
        items = [w for w in items if w["category"] == category]
    return {"items": items[:limit]}


@app.get("/widgets/{widget_id}")
async def get_widget(widget_id: str) -> Dict[str, str]:
    for widget in WIDGETS:
        if widget["id"] == widget_id:
            return widget
    raise HTTPException(status_code=404, detail="Widget not found")


@app.get("/search")
async def search_widgets(q: str = Query(..., min_length=1)) -> Dict[str, List[Dict[str, str]]]:
    term = q.lower()
    results = [
        w
        for w in WIDGETS
        if term in w["name"].lower() or term in w["category"].lower()
    ]
    return {"items": results}


@app.get("/stats")
async def get_stats() -> Dict[str, int]:
    total = len(WIDGETS)
    by_category: Dict[str, int] = {}
    for widget in WIDGETS:
        by_category[widget["category"]] = by_category.get(widget["category"], 0) + 1
    return {"total": total, "categories": len(by_category)}
