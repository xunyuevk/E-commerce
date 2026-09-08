"""P3 FastAPI 服务：/sessions 场次列表、/segments 切片查询、交互式 LLM 切片、/ 演示页。"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shopmind import db
from shopmind.config import get_settings
from shopmind.storage import get_minio

from .pipeline import _sentences_to_clauses, run_pipeline

app = FastAPI(title="ShopMind 直播切片洞察", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"
VIDEO_DIR = Path(__file__).resolve().parent / "data" / "videos"

# 后台切片任务登记：job_id -> {"running": bool, "result": dict|None, "error": str|None}
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

# 转写缓存：video -> clauses（避免每次交互切片都重复抽音频+ASR）
_CLAUES_CACHE: dict[str, list[dict]] = {}
_CLAUES_CACHE_LOCK = threading.Lock()


def _loads(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "shopmind-live-insight"}


@app.get("/sessions")
def sessions() -> list[dict]:
    rows = db.fetchall(
        "SELECT id, session_no, started_at, ended_at, asr_status "
        "FROM live_session ORDER BY id DESC LIMIT 50"
    )
    return [dict(r) for r in rows]


@app.get("/segments")
def segments(session_id: int) -> dict:
    sess = db.fetchone(
        "SELECT session_no FROM live_session WHERE id=:id", {"id": session_id}
    )
    rows = db.fetchall(
        "SELECT seq, start_sec, end_sec, topic, summary, sentiment, product_ids, clip_object_key "
        "FROM live_segment WHERE session_id=:id ORDER BY seq",
        {"id": session_id},
    )
    out = []
    for r in rows:
        d = dict(r)
        d["product_ids"] = _loads(r["product_ids"]) or []
        out.append(d)
    return {"session_no": sess["session_no"] if sess else None, "segments": out}


@app.get("/clip")
def clip(key: str) -> Response:
    """按 MinIO object_key 回放视频片段。"""
    client = get_minio()
    resp = client.get_object("shopmind", key)
    try:
        data = resp.read()
    finally:
        resp.close()
        resp.release_conn()
    return Response(content=data, media_type="video/mp4")


class SliceRequest(BaseModel):
    requirement: str | None = None
    seg_count: int | None = None
    video: str | None = None
    mode: str = "llm"  # llm = LLM 需求规划（默认） | rule = 关键词规则切分


@app.get("/video")
def video_list() -> dict:
    """当前可切片的视频列表（data/videos 下所有 mp4）。"""
    vids = sorted(p.name for p in VIDEO_DIR.glob("*.mp4")) if VIDEO_DIR.exists() else []
    return {"videos": vids}


def _get_video_path(video: str | None = None) -> Path:
    if video:
        p = VIDEO_DIR / video
        if p.exists():
            return p
        raise ValueError(f"视频不存在：{video}")
    vids = sorted(VIDEO_DIR.glob("*.mp4")) if VIDEO_DIR.exists() else []
    if not vids:
        raise ValueError("data/videos 下没有 mp4 视频，请先放入")
    return vids[0]


def _session_no_for(video: str | None) -> str:
    """为一次切片生成唯一的场次号：LS-<视频>-<HHMMSS>，每次切片都不同（不覆盖前次）。"""
    from datetime import datetime

    stem = Path(video).stem if video else "video"
    safe = "".join(ch if ch.isalnum() else "-" for ch in stem)[:40].strip("-") or "video"
    ts = datetime.now().strftime("%H%M%S")
    return f"LS-{safe}-{ts}"


def _run_slice_job(job_id: str, requirement: str, seg_count: int | None, video: str | None) -> None:
    """后台线程：跑 LLM 规划切片（复用 run_pipeline 的全流程：ASR→规划→切视频→落库）。"""
    try:
        video_path = str(_get_video_path(video))
        # 每次切片新建唯一场次，前端按场次列表区分"第几次切片"
        sess_no = _session_no_for(video)
        summary = run_pipeline(video_path=video_path, plan=requirement, seg_count=seg_count, session_no=sess_no)
        summary["session_no"] = sess_no
        with _JOBS_LOCK:
            _JOBS[job_id]["running"] = False
            _JOBS[job_id]["result"] = summary
    except Exception as exc:  # noqa: BLE001
        with _JOBS_LOCK:
            _JOBS[job_id]["running"] = False
            _JOBS[job_id]["error"] = str(exc)


@app.post("/slice")
def slice_video(req: SliceRequest) -> dict:
    """启动切片（后台跑，返回 job_id 供轮询）。mode=llm 走 LLM 需求规划（默认）；rule 走关键词规则。"""
    mode = (req.mode or "llm").strip().lower()
    if mode not in ("llm", "rule"):
        raise ValueError("mode 仅支持 llm/rule")
    if mode == "llm" and not (req.requirement or "").strip():
        raise ValueError("LLM 规划模式需要切分需求 requirement")
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"running": True, "result": None, "error": None}
    plan_req = (req.requirement or "").strip() if mode == "llm" else None
    t = threading.Thread(
        target=_run_slice_job, args=(job_id, plan_req, req.seg_count, req.video), daemon=True
    )
    t.start()
    return {"job_id": job_id}


@app.get("/slice-status/{job_id}")
def slice_status(job_id: str) -> dict:
    """轮询后台切片任务。"""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return {"running": False, "error": "job 不存在", "result": None}
        return dict(job)
