"""P4 人工审核（HITL）与发布：把状态机的外部事件落到人工动作。

为什么必须有 HITL：AI 生成内容可能被合规引擎漏判（规则只认字面词、LLM 有幻觉），
发布即对外，责任在人。因此 human_review 阶段状态机"停住"，必须由人 approve/reject 才继续，
approved 之后也必须再由人显式 publish，AI 不替人做最终决定。
"""
from __future__ import annotations

import json

from shopmind import db
from shopmind.ai import get_image_gen
from shopmind.lineage import add_lineage, record_audit
from shopmind.logging import get_logger
from shopmind.storage import put_bytes

from .state_machine import transition

log = get_logger("shopmind.p4.hitl")

DECISIONS: tuple[str, ...] = ("approve", "reject")
TEXT_TYPES: tuple[str, ...] = ("product_copy", "live_highlight")


def _loads(value):
    """JSON 列（pymysql 返回 str）安全反序列化。"""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _get_task(task_no: str) -> dict:
    row = db.fetchone("SELECT * FROM material_task WHERE task_no=:n", {"n": task_no})
    if row is None:
        raise ValueError(f"任务不存在：{task_no}")
    return row


def _set_state(task_id: int, state: str, step: str, **cols) -> None:
    sets = ["state=:state", "current_step=:step", "updated_at=NOW()"]
    params: dict = {"state": state, "step": step, "id": task_id}
    for key, val in cols.items():
        sets.append(f"{key}=:{key}")
        params[key] = val
    db.execute(f"UPDATE material_task SET {', '.join(sets)} WHERE id=:id", params)


def _set_state_if(task_id: int, from_state: str, state: str, step: str, **cols) -> bool:
    """原子更新：仅当当前状态 == from_state 时才更新为 state，返回是否成功抢占。

    这是发布/审核的并发保护——重复点击时只有一路能通过 WHERE state=from_state 抢到锁，
    `execute` 返回受影响的 rowcount，>0 即抢到。
    """
    sets = ["state=:state", "current_step=:step", "updated_at=NOW()"]
    params: dict = {"state": state, "step": step, "id": task_id, "from": from_state}
    for key, val in cols.items():
        sets.append(f"{key}=:{key}")
        params[key] = val
    affected = db.execute(
        f"UPDATE material_task SET {', '.join(sets)} WHERE id=:id AND state=:from", params
    )
    return affected > 0


def review(task_no: str, reviewer: str, decision: str, feedback: str | None = None) -> dict:
    """人工审核：仅 human_review 状态允许；approve → approved，reject → rejected。"""
    task = _get_task(task_no)
    if task["state"] != "human_review":
        raise ValueError(
            f"任务 {task_no} 当前状态为 {task['state']!r}，仅 human_review 状态可人工审核"
        )
    if decision not in DECISIONS:
        raise ValueError(f"decision 仅支持 {DECISIONS}，收到 {decision!r}")

    event = decision  # approve / reject 与事件同名
    new_state = transition("human_review", event)

    db.insert_get_id(
        "INSERT INTO material_review (task_id, reviewer, decision, feedback) "
        "VALUES (:t, :r, :d, :f)",
        {"t": task["id"], "r": reviewer, "d": decision, "f": feedback},
    )
    _set_state(task["id"], new_state, new_state, assignee=reviewer)
    record_audit(
        "p4", event,
        detail={"task_no": task_no, "from": "human_review", "to": new_state,
                "reviewer": reviewer, "feedback": feedback},
    )
    log.info("人工审核 %s → %s（%s）", task_no, new_state, reviewer)
    return {"task_no": task_no, "state": new_state, "decision": decision}


def publish(task_no: str) -> dict:
    """发布：仅 approved 状态允许；文本落 material_output，FAQ 回血 faq 表并记血缘。

    幂等保护：用原子更新 `UPDATE ... WHERE state='approved'` 抢占——并发/重复点击
    时只有一路能抢到（rowcount=1），其余返回已发布，避免重复生成配图/重复回血。
    """
    task = _get_task(task_no)
    # 已在终态（已被发布抢占），幂等返回
    if task["state"] in ("published", "failed", "rejected"):
        return {"task_no": task_no, "state": task["state"], "outputs": [], "idempotent": True}
    if task["state"] != "approved":
        raise ValueError(f"任务 {task_no} 当前状态为 {task['state']!r}，仅 approved 状态可发布")

    task_type = task["task_type"]
    result = _loads(task["result_json"]) or {}
    new_state = transition("approved", "publish")

    # 原子抢占：从 approved 推进到 published（只能成功一次），抢不到说明其他请求已发布
    claimed = _set_state_if(task["id"], "approved", new_state, new_state)
    if not claimed:
        log.info("任务 %s 已被并发发布抢占，幂等跳过", task_no)
        return {"task_no": task_no, "state": new_state, "outputs": [], "idempotent": True}

    outputs: list[dict] = []

    if task_type in TEXT_TYPES:
        content = json.dumps(result, ensure_ascii=False, indent=2)
        db.insert_get_id(
            "INSERT INTO material_output (task_id, content, content_type, status) "
            "VALUES (:t, :c, 'text', 'published')",
            {"t": task["id"], "c": content},
        )
        outputs.append({"content_type": "text"})
        # 可选配图：mock 文生图离线可跑，真实走 DashScope；配图失败不影响文本发布
        try:
            _publish_image(task_no, task["id"], _image_prompt(task_type, result))
            outputs.append({"content_type": "image"})
        except Exception as exc:  # noqa: BLE001
            log.warning("配图生成/上传失败（文本已发布，不影响主流程）：%s", exc)
    else:  # faq_expansion 回血
        _publish_faq(task, result)
        content = json.dumps(result, ensure_ascii=False, indent=2)
        db.insert_get_id(
            "INSERT INTO material_output (task_id, content, content_type, status) "
            "VALUES (:t, :c, 'text', 'published')",
            {"t": task["id"], "c": content},
        )
        faq_count = len(result) if isinstance(result, list) else 0
        outputs.append({"content_type": "text", "faq_count": faq_count})

    record_audit("p4", "publish", detail={"task_no": task_no, "from": "approved", "to": new_state, "outputs": outputs})
    log.info("发布完成 %s → %s，产出 %s", task_no, new_state, outputs)
    return {"task_no": task_no, "state": new_state, "outputs": outputs}


def _image_prompt(task_type: str, result: dict) -> str:
    title = result.get("title") if isinstance(result, dict) else None
    return f"电商素材配图：{title or task_type}"


def _publish_image(task_no: str, task_id: int, prompt: str) -> None:
    """生成配图写入 MinIO，并登记 material_output(image) 记录。"""
    data = get_image_gen().generate(prompt)
    key = f"p4/{task_no}/cover.png"
    put_bytes(key, data, "image/png")
    db.insert_get_id(
        "INSERT INTO material_output (task_id, content, content_type, object_key, status) "
        "VALUES (:t, NULL, 'image', :k, 'published')",
        {"t": task_id, "k": key},
    )


def _publish_faq(task: dict, faqs) -> None:
    """逐条回血 faq 表，并登记 material_output → faq 的血缘边。"""
    payload = _loads(task["input_json"]) or {}
    topic = payload.get("topic") if isinstance(payload, dict) else None

    items = faqs if isinstance(faqs, list) else []
    inserted = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question") or "").strip()
        a = str(item.get("answer") or "").strip()
        if not q or not a:
            # 真实小模型偶发输出空字段，回血前兜底，避免脏数据入库
            log.warning("跳过空字段 FAQ：question=%r answer=%r", q, a)
            continue
        tags = item.get("tags") or []
        tags_str = ",".join(str(t) for t in tags) if isinstance(tags, list) else str(tags or "")
        db.execute(
            "INSERT INTO faq (question, answer, category, tags, enabled) "
            "VALUES (:q, :a, :cat, :t, 1)",
            {
                "q": q,
                "a": a,
                "cat": item.get("category") or topic or "通用",
                "t": tags_str,
            },
        )
        inserted += 1
    add_lineage("material_output", "faq", "feeds", f"P4 任务 {task['task_no']} FAQ 回血")
