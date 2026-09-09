"""P4 FastAPI 服务：创建素材任务 / 推进 / 查看状态 / 演示页。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shopmind import db
from shopmind.storage import get_minio

from . import hitl
from .pipeline import advance, create_task

app = FastAPI(title="ShopMind 素材生产 Agent", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"

TASK_TYPES = ("product_copy", "live_highlight", "faq_expansion")


class NewTaskRequest(BaseModel):
    task_type: str
    product_id: int | None = None
    segment_id: int | None = None
    topic: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "shopmind-material-agent"}


@app.get("/products")
def products() -> list[dict]:
    rows = db.fetchall("SELECT id, name FROM product ORDER BY id")
    return [dict(r) for r in rows]


@app.get("/task-types")
def task_types() -> list[str]:
    return list(TASK_TYPES)


@app.post("/create")
def create(req: NewTaskRequest) -> dict:
    payload: dict = {}
    if req.task_type == "product_copy":
        if req.product_id is None:
            raise ValueError("product_copy 需要 product_id")
        payload = {"product_id": req.product_id}
    elif req.task_type == "live_highlight":
        if req.segment_id is None:
            raise ValueError("live_highlight 需要 segment_id")
        payload = {"segment_id": req.segment_id}
    elif req.task_type == "faq_expansion":
        if not req.topic:
            raise ValueError("faq_expansion 需要 topic")
        payload = {"topic": req.topic}
    task_no = create_task(req.task_type, payload)
    return {"task_no": task_no}


@app.post("/advance/{task_no}")
def advance_task(task_no: str) -> dict:
    row = db.fetchone("SELECT id FROM material_task WHERE task_no=:no", {"no": task_no})
    if row is None:
        raise ValueError(f"任务不存在：{task_no}")
    result = advance(row["id"])
    return {"task_no": task_no, "state": result.get("state"), "message": result.get("message")}


@app.get("/status/{task_no}")
def status(task_no: str) -> dict:
    row = db.fetchone("SELECT * FROM material_task WHERE task_no=:no", {"no": task_no})
    if row is None:
        raise ValueError(f"任务不存在：{task_no}")
    d = dict(row)
    d["result"] = _loads(d.pop("result_json", None))
    d["input"] = _loads(d.pop("input_json", None))
    # 附带产出记录（含 image object_key，供前端展示图片）
    outs = db.fetchall(
        "SELECT content_type, object_key, status FROM material_output "
        "WHERE task_id=:id ORDER BY id",
        {"id": row["id"]},
    )
    d["outputs"] = [dict(o) for o in outs]
    return d


class ReviewRequest(BaseModel):
    reviewer: str
    decision: str  # approve | reject
    feedback: str | None = None


@app.post("/review/{task_no}")
def review(task_no: str, req: ReviewRequest) -> dict:
    return hitl.review(task_no, req.reviewer, req.decision, req.feedback)


@app.post("/publish/{task_no}")
def publish(task_no: str) -> dict:
    return hitl.publish(task_no)


@app.get("/image")
def image(key: str) -> Response:
    """按 MinIO object_key 读取配图，供前端 <img> 展示。"""
    client = get_minio()
    resp = client.get_object("shopmind", key)
    try:
        data = resp.read()
    finally:
        resp.close()
        resp.release_conn()
    return Response(content=data, media_type="image/png")


def _loads(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value
