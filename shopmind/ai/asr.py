"""ASR：阿里云 / 腾讯云录音文件识别 + mock 回退。

mock 回退 = 直接读取转写文本文件（跳过声学模型），用于离线演示整条流水线；
接真实音频时切 aliyun/tencent（需装对应 SDK + 配 AK，见各项目 README）。
"""
from __future__ import annotations

from pathlib import Path

from ..config import get_settings
from ..logging import get_logger
from .base import ASR

log = get_logger("shopmind.ai.asr")


class MockASR:
    """离线回退：把 audio_ref 当作转写文本文件路径，直接读内容。"""

    def transcribe(self, audio_ref: str, **kwargs) -> str:
        p = Path(audio_ref)
        if not p.exists():
            raise FileNotFoundError(f"mock ASR 需要转写文本文件，找不到：{audio_ref}")
        return p.read_text(encoding="utf-8").strip()


class AliyunFileTransASR:
    """阿里云录音文件识别（官方 SDK aliyun-python-sdk-nls-filetrans）。

    安装：pip install aliyun-python-sdk-core aliyun-python-sdk-nls-filetrans
    流程：提交任务 → 轮询 → 取转写结果。
    """

    def __init__(self, ak_id: str, ak_secret: str, app_key: str):
        self.ak_id, self.ak_secret, self.app_key = ak_id, ak_secret, app_key

    def transcribe(self, audio_ref: str, **kwargs) -> str:
        try:
            from aliyunsdkcore.client import AcsClient  # noqa: PLC0415
            from aliyunsdknls_filetrans.request.v20180817 import SubmitTaskRequest, GetTaskResultRequest  # noqa: PLC0415
        except ImportError as e:
            raise ImportError("阿里云 ASR 需先安装 SDK：pip install aliyun-python-sdk-core aliyun-python-sdk-nls-filetrans") from e

        import time

        client = AcsClient(self.ak_id, self.ak_secret, "cn-shanghai")

        submit = SubmitTaskRequest.SubmitTaskRequest()
        submit.set_FileLink(audio_ref)  # 需为可公网访问的音频 URL（或 OSS）
        submit.set_AppKey(self.app_key)
        submit.set_Task(json={"enable_punctuation_prediction": True})
        task_id = client.do_action_with_exception(submit).decode("utf-8")

        for _ in range(120):
            get = GetTaskResultRequest.GetTaskResultRequest()
            get.set_Task(task_id)
            resp = client.do_action_with_exception(get).decode("utf-8")
            import json

            data = json.loads(resp)
            if data.get("StatusText") == "SUCCESS":
                return data.get("Result", "")
            if data.get("StatusText") == "ERROR":
                raise RuntimeError(f"阿里云 ASR 失败：{data}")
            time.sleep(3)
        raise TimeoutError("阿里云 ASR 超时")


class TencentASR:
    """腾讯云录音文件识别（tencentcloud-sdk-python）。

    安装：pip install tencentcloud-sdk-python
    流程：CreateRecTask 提交 → DescribeTaskStatus 轮询。
    """

    def __init__(self, secret_id: str, secret_key: str):
        self.secret_id, self.secret_key = secret_id, secret_key

    def transcribe(self, audio_ref: str, **kwargs) -> str:
        try:
            from tencentcloud.asr.v20190614 import asr_client, models  # noqa: PLC0415
            from tencentcloud.common import credential  # noqa: PLC0415
        except ImportError as e:
            raise ImportError("腾讯云 ASR 需先安装 SDK：pip install tencentcloud-sdk-python") from e

        import time

        cred = credential.Credential(self.secret_id, self.secret_key)
        client = asr_client.AsrClient(cred, "ap-guangzhou")

        req = models.CreateRecTaskRequest()
        req.EngineModelType = "16k_zh"
        req.ChannelNum = 1
        req.ResTextFormat = 3
        req.SourceType = 0
        req.Url = audio_ref
        resp = client.CreateRecTask(req)
        task_id = resp.Data.TaskId

        for _ in range(120):
            q = models.DescribeTaskStatusRequest()
            q.TaskId = task_id
            r = client.DescribeTaskStatus(q)
            if r.Data.StatusStr == "success":
                return r.Data.Result
            if r.Data.Status == 3:
                raise RuntimeError(f"腾讯云 ASR 失败：{r.Data.ErrorMsg}")
            time.sleep(3)
        raise TimeoutError("腾讯云 ASR 超时")


class DashScopeParaformerASR:
    """百炼 Paraformer 实时语音识别（dashscope SDK，非流式 call 本地音频）。

    返回带时间戳的句子列表 list[dict]，每项 {start_sec, end_sec, text}。
    要求音频为 16k 单声道 PCM wav（上层用 ffmpeg 转好）。
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

    def transcribe(self, audio_ref: str, **kwargs) -> list[dict]:
        import dashscope  # noqa: PLC0415
        from http import HTTPStatus

        from dashscope.audio.asr import Recognition  # noqa: PLC0415

        dashscope.api_key = self.api_key
        recognition = Recognition(
            model="paraformer-realtime-v2",
            format="wav",
            sample_rate=16000,
            language_hints=["zh", "en"],
            callback=None,
        )
        result = recognition.call(audio_ref)
        if result.status_code != HTTPStatus.OK:
            raise RuntimeError(f"Paraformer ASR 失败：{result.status_code} {result.message}")

        sentences = result.get_sentence()
        out: list[dict] = []
        if isinstance(sentences, list):
            for s in sentences:
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                out.append({
                    "start_sec": round((s.get("begin_time") or 0) / 1000.0, 2),
                    "end_sec": round((s.get("end_time") or 0) / 1000.0, 2),
                    "text": text,
                    # 字级时间戳（含标点），供细粒度切分 / LLM 规划使用
                    "words": s.get("words") or [],
                })
        return out


_cached: ASR | None = None


def get_asr() -> ASR:
    global _cached
    if _cached is None:
        s = get_settings()
        p = s.asr_provider.strip().lower()
        if p == "mock":
            _cached = MockASR()
        elif p == "aliyun":
            _cached = AliyunFileTransASR(s.aliyun_asr_access_key_id, s.aliyun_asr_access_key_secret, s.aliyun_asr_app_key)
        elif p == "tencent":
            _cached = TencentASR(s.tencent_asr_secret_id, s.tencent_asr_secret_key)
        elif p == "dashscope":
            _cached = DashScopeParaformerASR(s.dashscope_api_key)
        else:
            raise ValueError(f"未知 ASR_PROVIDER：{s.asr_provider}")
    return _cached
