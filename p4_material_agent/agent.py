"""P4 素材生成：按任务类型组装提示词调用 LLM，mock 下返回结构化占位结果。

真实模式：让 LLM 输出 JSON，再 json.loads 解析成目标结构（prompt 里给出 schema）。
mock 模式：get_llm() 返回的是 "[mock] ..." 占位串，无法解析，因此直接基于 DB 数据
  构造结构化结果，并统一给文案字段加 "[mock] " 前缀，明确标注离线回退，
  避免与真实生成内容混淆。

返回结构约定：
  - product_copy   -> dict{"title", "selling_points": list[str], "copy"}
  - live_highlight -> dict{"title", "tags": list[str], "hook"}
  - faq_expansion  -> list[dict{"question", "answer"}]
"""
from __future__ import annotations

import json

from shopmind import db
from shopmind.ai import get_llm
from shopmind.config import get_settings
from shopmind.logging import get_logger

log = get_logger("shopmind.p4.agent")

TASK_TYPES: tuple[str, ...] = ("product_copy", "live_highlight", "faq_expansion")

# 结构化输出统一约束：真实 LLM 偶尔会带解释/代码围栏/未转义引号，靠提示词 + 容错解析兜底。
_JSON_RULE = (
    "输出要求：只输出一个合法的 JSON，不要输出任何解释、前后缀文字或 markdown 代码块；"
    "字符串内不要出现未转义的双引号或换行。"
)


def generate(task_type: str, input_payload: dict) -> dict | list[dict]:
    """按任务类型生成素材，返回结构化结果（mock 时带 "[mock]" 标注）。"""
    if task_type not in TASK_TYPES:
        raise ValueError(f"未知任务类型 {task_type!r}；可选：{', '.join(TASK_TYPES)}")

    if get_settings().use_mock:
        return _generate_mock(task_type, input_payload)
    return _generate_real(task_type, input_payload)


# ---------------------------------------------------------------------------
# 取数 + 提示词
# ---------------------------------------------------------------------------

def _fetch_product(product_id: int) -> dict:
    row = db.fetchone(
        "SELECT id, sku, name, category, brand, price, stock, description, specs_json "
        "FROM product WHERE id=:id",
        {"id": product_id},
    )
    if row is None:
        raise ValueError(f"商品不存在：product_id={product_id}")
    return row


def _fetch_segment(segment_id: int) -> dict:
    row = db.fetchone(
        "SELECT id, topic, summary, transcript, sentiment FROM live_segment WHERE id=:id",
        {"id": segment_id},
    )
    if row is None:
        raise ValueError(f"直播切片不存在：segment_id={segment_id}")
    return row


def _prompt_product(row: dict) -> str:
    return (
        "为下面商品生成营销文案，输出 JSON 对象，字段："
        "title(标题)、selling_points(卖点字符串数组)、copy(短文案)。\n"
        f"商品：{row['name']}（品牌 {row.get('brand') or '-'}，类目 {row.get('category') or '-'}，"
        f"价格 {row['price']}，规格 {row.get('specs_json') or '-'}）\n"
        f"描述：{row.get('description') or '-'}\n"
        f"{_JSON_RULE}"
    )


def _prompt_highlight(seg: dict) -> str:
    transcript = (seg.get("transcript") or "")[:500]
    return (
        "为下面直播切片生成引流素材，输出 JSON 对象，字段："
        "title(切片标题)、tags(标签字符串数组)、hook(引流文案)。\n"
        f"主题：{seg.get('topic') or '-'}\n"
        f"摘要：{seg.get('summary') or '-'}\n"
        f"转写节选：{transcript or '-'}\n"
        f"{_JSON_RULE}"
    )


def _prompt_faq(topic: str) -> str:
    return (
        f"围绕主题「{topic}」生成 3 条 FAQ，输出 JSON 对象，"
        f"唯一字段 items 是一个数组，含 3 项，每项含 question 与 answer 两个字段。\n{_JSON_RULE}"
    )


# ---------------------------------------------------------------------------
# mock：结构化 + "[mock]" 标注（离线回退）
# ---------------------------------------------------------------------------

def _generate_mock(task_type: str, payload: dict) -> dict | list[dict]:
    if task_type == "product_copy":
        row = _fetch_product(payload["product_id"])
        name = row["name"]
        brand = row.get("brand") or "精选品牌"
        return {
            "title": f"[mock] {name}",
            "selling_points": [
                f"[mock] {brand} 品质出品",
                f"[mock] 精选好物，到手价 ¥{row['price']}",
            ],
            "copy": f"[mock] {name}，{row.get('description') or '品质之选'}，价格 ¥{row['price']}，喜欢别错过。",
        }
    if task_type == "live_highlight":
        seg = _fetch_segment(payload["segment_id"])
        topic = seg.get("topic") or "直播切片"
        return {
            "title": f"[mock] {topic}",
            "tags": ["[mock] 直播", "[mock] 好物"],
            "hook": f"[mock] 主播讲解：{(seg.get('summary') or '')[:60]}",
        }
    # faq_expansion
    topic = payload.get("topic") or "通用"
    return [
        {"question": f"[mock] {topic}是什么？", "answer": f"[mock] {topic}是指……（离线占位答案）"},
        {"question": f"[mock] {topic}怎么用？", "answer": "[mock] 请按说明书或咨询客服使用（离线占位答案）"},
        {"question": f"[mock] {topic}有什么优势？", "answer": "[mock] 满足日常需求，具体以实际商品为准（离线占位答案）"},
    ]


# ---------------------------------------------------------------------------
# 真实：LLM 输出 JSON 再 parse
# ---------------------------------------------------------------------------

def _generate_real(task_type: str, payload: dict) -> dict | list[dict]:
    if task_type == "product_copy":
        row = _fetch_product(payload["product_id"])
        prompt = _prompt_product(row)
    elif task_type == "live_highlight":
        seg = _fetch_segment(payload["segment_id"])
        prompt = _prompt_highlight(seg)
    else:
        prompt = _prompt_faq(payload.get("topic") or "通用")

    # 结构化生成：json_object 模式 + 低温，显著降低格式漂移与“多嘴”
    chat_kwargs = {"temperature": 0.2, "response_format": {"type": "json_object"}}
    raw = get_llm().chat([{"role": "user", "content": prompt}], **chat_kwargs)
    try:
        parsed = _parse_json(raw)
    except ValueError:
        # 自纠一次：把上次（解析失败）的输出作为上下文，要求只重发合法 JSON
        raw2 = get_llm().chat(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "你上面的输出不是合法 JSON。请重新只输出一个合法 JSON（无任何额外文字、无 markdown、无代码围栏）。"},
            ],
            temperature=0.1,
        )
        parsed = _parse_json(raw2)

    # faq 提示词要求输出 {items:[...]}，这里归一化成下游期望的 list[dict]
    if task_type == "faq_expansion" and isinstance(parsed, dict):
        items = parsed.get("items")
        if isinstance(items, list):
            return items
    return parsed


def _parse_json(raw: str) -> dict | list[dict]:
    """解析 LLM 返回的 JSON：先剥 ```json 围栏，再容错提取最外层 {} 或 []。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 容错：模型偶尔在 JSON 前后夹带解释文字，取最外层结构再解析
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    log.warning("LLM 输出非合法 JSON，原文前 200 字：%s", text[:200])
    raise ValueError("LLM 输出解析失败（已尝试剥离围栏与最外层结构）")
