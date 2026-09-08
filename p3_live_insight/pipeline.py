"""P3 流水线编排：ASR → 语义分段 → 摘要/情感/商品关联 → 回血知识库 → 血缘审计。

这是「直播切片洞察引擎」的主流程：直播转写进来，切成商品粒度片段，
产出结构化洞察写回 live_segment，并每段回血一条 knowledge_doc 供 P2 检索。
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from shopmind import db
from shopmind.ai import get_asr
from shopmind.config import get_settings
from shopmind.lineage import (
    add_lineage,
    get_or_create_asset,
    record_audit,
    update_asset_row_count,
)
from shopmind.logging import get_logger
from shopmind.storage import ensure_bucket, put_bytes, put_text

from .clipper import clip_segment
from .llm_planner import plan_segments
from .product_link import link_products
from .segmenter import segment, sentiment, summarize

log = get_logger("p3")

ROOM_ID = "RM-001"
ROOM_TITLE = "小音官方旗舰店直播间"
ROOM_ANCHOR = "主播小音"
SESSION_NO = "LS-20240101-001"


def _sample_path() -> Path:
    """mock ASR 读取的本地转写文本绝对路径。"""
    return Path(__file__).resolve().parent / "data" / "sample_live.txt"


def _sec_to_mmss(sec: float) -> str:
    """秒 → MM:SS（segmenter 解析转写行用的格式）。"""
    m = int(sec) // 60
    s = int(sec) % 60
    return f"{m:02d}:{s:02d}"


def _sentences_to_transcript(sentences: list[dict]) -> str:
    """把带时间戳句子列表转成 'MM:SS 主播：内容' 文本，供 segmenter 解析。

    Paraformer 不做说话人分离，统一标「主播」；真实场景可再接 diarization。
    """
    lines = []
    for s in sentences:
        mmss = _sec_to_mmss(s["start_sec"])
        lines.append(f"{mmss} 主播：{s['text']}")
    return "\n".join(lines)


def _sentences_to_clauses(sentences: list[dict]) -> list[dict]:
    """用 ASR 字级时间戳 + 标点把长句切成细粒度子句，返回带 index/时间戳的列表。

    用于 LLM 规划切分：Paraformer 默认 VAD 断句很粗（连续口播可能 60s 一句），
    但 words 字段带字级时间戳与标点，按 。！？ 切子句能得到几十条细粒度单元。
    """
    clauses: list[dict] = []
    buf: list[str] = []
    buf_start: float | None = None
    for s in sentences:
        words = s.get("words") or []
        for w in words:
            text = w.get("text") or ""
            punct = w.get("punctuation") or ""
            bt = (w.get("begin_time") or 0) / 1000.0
            et = (w.get("end_time") or 0) / 1000.0
            if buf_start is None:
                buf_start = bt
            buf.append(text + punct)
            if punct in ("。", "！", "？"):
                clause_text = "".join(buf).strip()
                if clause_text:
                    clauses.append({
                        "start_sec": round(buf_start or bt, 2),
                        "end_sec": round(et, 2),
                        "text": clause_text,
                    })
                buf = []
                buf_start = None
    if buf:
        clauses.append({
            "start_sec": round(buf_start or 0, 2),
            "end_sec": round((sentences[-1].get("end_sec") if sentences else 0), 2),
            "text": "".join(buf).strip(),
        })
    for i, c in enumerate(clauses):
        c["index"] = i + 1
    return clauses


def _extract_audio(video_path: str) -> str:
    """ffmpeg 从视频抽 16k 单声道 PCM wav，返回临时文件路径（Paraformer 要求）。"""
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    import os

    os.close(fd)
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        wav_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 抽音频失败：{proc.stderr.decode('utf-8', 'ignore')[-200:]}")
    return wav_path


def _ensure_room() -> int:
    """建/取直播间，返回 live_room.id。"""
    row = db.fetchone("SELECT id FROM live_room WHERE room_id=:rid", {"rid": ROOM_ID})
    if row is not None:
        return int(row["id"])
    return db.insert_get_id(
        "INSERT INTO live_room (room_id, title, anchor) VALUES (:rid, :title, :anchor)",
        {"rid": ROOM_ID, "title": ROOM_TITLE, "anchor": ROOM_ANCHOR},
    )


def _ensure_session(room_id: int, session_no: str) -> int:
    """建/取直播场次，返回 live_session.id（初始 asr_status=transcribing）。"""
    row = db.fetchone("SELECT id FROM live_session WHERE session_no=:no", {"no": session_no})
    if row is not None:
        return int(row["id"])
    now = datetime.now()
    return db.insert_get_id(
        "INSERT INTO live_session (room_id, session_no, started_at, ended_at, asr_status) "
        "VALUES (:rid, :no, :start, :end, 'transcribing')",
        {"rid": room_id, "no": session_no, "start": now, "end": now},
    )


def _session_no_from_video(video_path: str | None) -> str:
    """从视频文件名派生场次号，让不同视频各占一个场次（互不覆盖）。

    trailer.mp4 → LS-trailer；缺省（mock 文本）用固定 SESSION_NO。
    """
    if not video_path:
        return SESSION_NO
    stem = Path(video_path).stem
    # 场次号只保留安全字符（文件名可能带空格/中文/特殊字符）
    safe = "".join(ch if ch.isalnum() else "-" for ch in stem)[:40].strip("-")
    return f"LS-{safe}" if safe else SESSION_NO


def run_pipeline(video_path: str | None = None, plan: str | None = None, seg_count: int | None = None, session_no: str | None = None) -> dict:
    """执行完整 P3 流水线，返回汇总结果。

    video_path：本地视频文件路径（可选）。
      - 提供 + ASR_PROVIDER=dashscope：ffmpeg 抽音频 → Paraformer 真实 ASR
        （带时间戳）→ 切文本段 + 切视频片段；
      - 提供 + ASR_PROVIDER=mock：读本地转写 txt 定时间戳，用 ffmpeg 切视频片段；
      - 缺省：仅文本切片（mock）。

    plan：用户切分需求（可选）。提供时走 LLM 规划切分（按需求自由切段），
      需真实 ASR（有字级时间戳）；缺省走原关键词规则切分。
    seg_count：LLM 规划切分的段数（可选）。缺省自动选 4~5 大段。
    session_no：场次号（可选）。缺省按视频文件名派生，不同视频各占一场次。
    """
    import os

    # 场次号：显式传入 > 从视频名派生 > 固定默认
    sess_no = session_no or _session_no_from_video(video_path)

    db.wait_for_mysql()
    ensure_bucket()

    room_id = _ensure_room()
    session_id = _ensure_session(room_id, sess_no)

    # ① ASR：mock 读本地 txt；dashscope 走 Paraformer 真实识别（带时间戳）
    use_real_asr = get_settings().asr_provider.strip().lower() == "dashscope"
    wav_path = None
    sentences: list[dict] | None = None
    if use_real_asr and video_path:
        wav_path = _extract_audio(video_path)
        sentences = get_asr().transcribe(wav_path)
        transcript = _sentences_to_transcript(sentences) if sentences else ""
    else:
        transcript = get_asr().transcribe(str(_sample_path()))

    transcript_object_key = f"live/{sess_no}.txt"
    put_text(transcript_object_key, transcript)

    # 时长估算：真实 ASR 用最后一句结束时间；mock 用句数 * 3 秒
    if sentences:
        duration_sec = sentences[-1]["end_sec"]
    else:
        duration_sec = len([ln for ln in transcript.splitlines() if ln.strip()]) * 3
    db.execute(
        "UPDATE live_session SET transcript_object_key=:k, duration_sec=:d, "
        "asr_status='done', ended_at=NOW() WHERE id=:id",
        {"k": transcript_object_key, "d": duration_sec, "id": session_id},
    )

    # ② 语义分段（两路：LLM 规划切分 / 原关键词规则切分）+ 摘要/情感 + 商品关联
    if plan and sentences:
        # LLM 规划：字级时间戳 → 细粒度子句 → LLM 按需求分组 → 映射回时间戳
        clauses = _sentences_to_clauses(sentences)
        plan_result = plan_segments(clauses, plan, seg_count)
        segments = []
        for idx, item in enumerate(plan_result, start=1):
            s_idx, e_idx = item["start_idx"], item["end_idx"]
            seg_clauses = [c for c in clauses if s_idx <= c["index"] <= e_idx]
            segments.append({
                "seq": idx,
                "start_sec": seg_clauses[0]["start_sec"],
                "end_sec": seg_clauses[-1]["end_sec"],
                "transcript": "\n".join(c["text"] for c in seg_clauses),
                "topic": item["topic"],
            })
    else:
        segments = segment(transcript)

    segments = link_products(segments)
    for seg in segments:
        seg["summary"] = summarize(seg["transcript"], seg["topic"])
        seg["sentiment"] = sentiment(seg["transcript"])

    # ⑤ 落库 live_segment：先清空该场次旧切片（重跑幂等），再逐段写入
    db.execute("DELETE FROM live_segment WHERE session_id=:sid", {"sid": session_id})
    clipped = 0
    for seg in segments:
        # 若提供本地视频，用 ffmpeg 按该段转写时间戳切出视频片段存入 MinIO
        # （每次切片一个独立子目录 live/clips/<session_no>/<seq>.mp4）
        clip_key = None
        if video_path:
            clip_bytes = clip_segment(video_path, seg["start_sec"], seg["end_sec"])
            if clip_bytes is not None:
                clip_key = f"live/clips/{sess_no}/{seg['seq']}.mp4"
                put_bytes(clip_key, clip_bytes, "video/mp4")
                clipped += 1
        db.insert_get_id(
            "INSERT INTO live_segment "
            "(session_id, seq, start_sec, end_sec, transcript, topic, summary, "
            " sentiment, product_ids, clip_object_key, status) "
            "VALUES (:sid, :seq, :ss, :es, :tr, :topic, :sum, :sent, :pids, :clip, 'segmented')",
            {
                "sid": session_id,
                "seq": seg["seq"],
                "ss": seg["start_sec"],
                "es": seg["end_sec"],
                "tr": seg["transcript"],
                "topic": seg["topic"],
                "sum": seg["summary"],
                "sent": seg["sentiment"],
                "pids": json.dumps(seg["product_ids"]),
                "clip": clip_key,
            },
        )

    # ⑥ 回血：每段生成一条 knowledge_doc，正文进 MinIO，元数据进 MySQL
    for seg in segments:
        content = (
            f"# {seg['topic']}\n\n"
            f"- 摘要：{seg['summary']}\n"
            f"- 情感：{seg['sentiment']}\n\n"
            f"## 口播转写\n\n{seg['transcript']}\n"
        )
        key = f"knowledge/live/{sess_no}/{seg['seq']}.md"
        put_text(key, content)
        db.execute(
            "INSERT INTO knowledge_doc (title, source_type, object_key, doc_meta, status) "
            "VALUES (:t, 'live_transcript', :k, :meta, 'staged')",
            {
                "t": f"直播：{seg['topic']}",
                "k": key,
                "meta": json.dumps(
                    {"category": "直播切片", "product_ids": seg["product_ids"]},
                    ensure_ascii=False,
                ),
            },
        )

    # ⑦ 资产 / 血缘 / 审计
    asset_id = get_or_create_asset(
        "live_segment", "table", "mysql:shopmind.live_segment", owner="p3", sensitivity="L3"
    )
    total = db.fetchone("SELECT COUNT(*) AS c FROM live_segment")["c"]
    update_asset_row_count("live_segment", int(total))
    add_lineage("live_session", "live_segment", "derives_from", "ASR→语义分段")
    add_lineage("live_segment", "knowledge_doc", "feeds", "直播切片回血知识库")
    record_audit(
        "p3", "run_pipeline", asset_id,
        {"session_no": sess_no, "segments": len(segments)},
    )

    # 清理真实 ASR 的临时音频文件
    if wav_path:
        try:
            os.remove(wav_path)
        except OSError:
            pass

    summary = {
        "room_id": ROOM_ID,
        "session_no": sess_no,
        "transcript_chars": len(transcript),
        "segments": len(segments),
        "knowledge_docs": len(segments),
        "video_clips": clipped if video_path else None,
    }
    log.info("P3 流水线完成：%s", json.dumps(summary, ensure_ascii=False, default=str))
    return summary
