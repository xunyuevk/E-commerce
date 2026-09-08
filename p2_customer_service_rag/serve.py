"""P2 FastAPI 服务：/chat 问答、/health 健康检查、/ 演示页。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .pipeline import answer

app = FastAPI(title="ShopMind 智能客服 RAG", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ChatRequest(BaseModel):
    query: str
    use_cache: bool = True


class Source(BaseModel):
    title: str
    chunk_id: int
    source_type: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    answerable: bool
    confidence: float
    sources: list[Source]
    from_cache: bool
    matched_query: str | None
    latency_ms: int


@app.get("/")
def index() -> FileResponse:
    """演示页（浏览器访问 http://127.0.0.1:8000/）。"""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "shopmind-customer-service-rag"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    return answer(req.query, use_cache=req.use_cache)
