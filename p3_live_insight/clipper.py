"""P3 视频切片：用 ffmpeg 按 start_sec/end_sec 从本地视频切出片段字节。

设计（面试可讲）：
  - 切片边界来自 segmenter 解析的转写时间戳（start_sec/end_sec），
    天然对齐主播讲解的商品粒度，而非固定时长硬切；
  - 用 ffmpeg -ss/-to 做流拷贝重编码，输出 mp4 字节流到 stdout，
    由上层直接写 MinIO（不进中间磁盘），避免临时文件与二次 IO；
  - ffmpeg 不可用 / 视频缺失时优雅降级（返回 None），不阻断文本切片主链路。
"""
from __future__ import annotations

import shutil
import subprocess

from shopmind.logging import get_logger

log = get_logger("shopmind.p3.clipper")


def ffmpeg_available() -> bool:
    """本机是否可用 ffmpeg（在 PATH 中）。"""
    return shutil.which("ffmpeg") is not None


def clip_segment(
    video_path: str,
    start_sec: float,
    end_sec: float,
    pad_sec: float = 0.0,
) -> bytes | None:
    """从本地视频切出 [start_sec, end_sec] 片段，返回 mp4 字节；失败返回 None。

    pad_sec：片段边界前后各留的缓冲秒数（默认 0，即严格按转写时间戳）。
    """
    import os
    import tempfile

    if not ffmpeg_available():
        log.warning("ffmpeg 不可用，跳过视频切片（仅保留文本切片）")
        return None

    start = max(0.0, start_sec - pad_sec)
    duration = max(0.5, (end_sec - start_sec) + 2 * pad_sec)
    # 输出到临时文件（可 seek），产出【标准 mp4，+faststart 把 moov 移文件头】。
    # 这样浏览器 <video> 能正确识别总时长、可拖动；stdout 管道不可 seek 只能产出
    # fragmented mp4（时长会被浏览器误判，造成"只播几秒"）。
    fd, tmp_out = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        "-f", "mp4", tmp_out,
    ]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("ffmpeg 切片失败（%s）：%s", video_path, exc)
        _safe_rm(tmp_out)
        return None

    if proc.returncode != 0:
        log.warning("ffmpeg 切片失败（exit=%s）：%s", proc.returncode, proc.stderr.decode("utf-8", "ignore")[-200:])
        _safe_rm(tmp_out)
        return None

    try:
        with open(tmp_out, "rb") as f:
            data = f.read()
    finally:
        _safe_rm(tmp_out)
    if not data:
        log.warning("ffmpeg 切片输出为空：%s", video_path)
        return None
    return data


def _safe_rm(path: str) -> None:
    import os

    try:
        os.remove(path)
    except OSError:
        pass
