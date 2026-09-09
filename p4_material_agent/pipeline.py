"""P4 任务流水线：创建任务 + 单步推进（显式状态机驱动）。

advance 只推进"一步"，由 CLI 的 run 命令循环调用直到 human_review 或终态；
这样每个状态迁移都可审计、可打断，天然适配 HITL（human_review 阶段不自动过）。

约定：current_step 冗余记录当前所处阶段，等价于 state 的机器可读副本，
方便没有状态机代码时也能直接 SQL 查询 / 过滤。
"""
from __future__ import annotations

import json
import time

from shopmind import db
from shopmind.lineage import record_audit
from shopmind.logging import get_logger

from . import agent
from .compliance import combined_check
from .state_machine import is_terminal, transition

log = get_logger("shopmind.p4.pipeline")

TASK_TYPES: tuple[str, ...] = ("product_copy", "live_highlight", "faq_expansion")


def _loads(value):
    """JSON 列（pymysql 返回 str）安全反序列化；已为 dict/list 则原样返回。"""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _update(task_id: int, state: str, step: str, **cols) -> None:
    """按需拼 SET 更新任务状态；列名来自内部受控键，参数化防注入。"""
    sets = ["state=:state", "current_step=:step", "updated_at=NOW()"]
    params: dict = {"state": state, "step": step, "id": task_id}
    for key, val in cols.items():
        sets.append(f"{key}=:{key}")
        params[key] = val
    db.execute(f"UPDATE material_task SET {', '.join(sets)} WHERE id=:id", params)


def _audit(task_no: str, event: str, old_state: str, new_state: str, **extra) -> None:
    record_audit(
        "p4", event,
        detail={"task_no": task_no, "from": old_state, "to": new_state, **extra},
    )


def create_task(task_type: str, input_payload: dict) -> str:
    """创建任务并推进到 generating，返回 task_no。

    task_no 形如 MT-{type}-{YYYYmmddHHMMSS}。
    """
    if task_type not in TASK_TYPES:
        raise ValueError(f"未知任务类型 {task_type!r}；可选：{', '.join(TASK_TYPES)}")

    task_no = f"MT-{task_type}-{time.strftime('%Y%m%d%H%M%S')}"
    task_id = db.insert_get_id(
        "INSERT INTO material_task (task_no, task_type, input_json, state, current_step) "
        "VALUES (:no, :t, :ij, 'draft', 'created')",
        {"no": task_no, "t": task_type, "ij": json.dumps(input_payload, ensure_ascii=False)},
    )
    new_state = transition("draft", "start")
    _update(task_id, new_state, new_state)
    _audit(task_no, "start", "draft", new_state, task_type=task_type)
    log.info("创建素材任务 %s（%s）→ %s", task_no, task_type, new_state)
    return task_no


def advance(task_id: int) -> dict:
    """按当前状态执行一步并推进，返回本次执行结果摘要。"""
    row = db.fetchone("SELECT * FROM material_task WHERE id=:id", {"id": task_id})
    if row is None:
        raise ValueError(f"任务不存在：task_id={task_id}")

    state = row["state"]
    task_no = row["task_no"]

    if state == "generating":
        return _step_generate(row)
    if state == "compliance_check":
        return _step_compliance(row)
    if state == "human_review":
        return {
            "task_id": task_id, "task_no": task_no, "state": "human_review",
            "action": None, "message": "等待人工审核（不自动推进）",
            "compliance": row.get("compliance"), "hits": [], "assignee": row.get("assignee"),
        }
    if is_terminal(state):
        return {
            "task_id": task_id, "task_no": task_no, "state": state,
            "action": None, "message": f"任务已处于终态 {state}",
            "compliance": row.get("compliance"), "hits": [], "assignee": row.get("assignee"),
        }
    raise ValueError(f"状态 {state!r} 无自动推进动作（请检查任务创建流程）")


def _step_generate(row: dict) -> dict:
    """generating → 生成素材 → compliance_check（或 error → failed）。"""
    task_id = row["id"]
    try:
        payload = _loads(row["input_json"]) or {}
        result = agent.generate(row["task_type"], payload)
    except Exception as exc:  # noqa: BLE001
        new_state = transition("generating", "error")
        _update(task_id, new_state, new_state, error=str(exc))
        _audit(row["task_no"], "error", "generating", new_state, error=str(exc))
        log.exception("生成失败：%s", row["task_no"])
        return {
            "task_id": task_id, "task_no": row["task_no"], "state": new_state,
            "action": "error", "message": f"生成失败：{exc}",
            "compliance": None, "hits": [], "assignee": None,
        }

    new_state = transition("generating", "generated")
    _update(task_id, new_state, new_state, result_json=json.dumps(result, ensure_ascii=False), error=None)
    _audit(row["task_no"], "generated", "generating", new_state)
    return {
        "task_id": task_id, "task_no": row["task_no"], "state": new_state,
        "action": "generated", "message": "素材已生成，进入合规检查",
        "compliance": None, "hits": [], "assignee": None,
    }


def _step_compliance(row: dict) -> dict:
    """compliance_check → 双通道合规 → human_review / rejected（或 error → failed）。"""
    task_id = row["id"]
    result = _loads(row["result_json"]) or {}
    text = _extract_text(row["task_type"], result)

    try:
        compliance, hits = combined_check(text)
    except Exception as exc:  # noqa: BLE001
        new_state = transition("compliance_check", "error")
        _update(task_id, new_state, new_state, error=str(exc))
        _audit(row["task_no"], "error", "compliance_check", new_state, error=str(exc))
        log.exception("合规检查失败：%s", row["task_no"])
        return {
            "task_id": task_id, "task_no": row["task_no"], "state": new_state,
            "action": "error", "message": f"合规检查失败：{exc}",
            "compliance": None, "hits": [], "assignee": None,
        }

    if compliance == "pass":
        event, assignee = "compliance_pass", None
    elif compliance == "fail":
        event, assignee = "compliance_fail", None
    else:  # review
        event, assignee = "compliance_review", "合规复核员"

    new_state = transition("compliance_check", event)
    _update(task_id, new_state, new_state, compliance=compliance, assignee=assignee)
    _audit(row["task_no"], event, "compliance_check", new_state, compliance=compliance, hits=hits)

    return {
        "task_id": task_id, "task_no": row["task_no"], "state": new_state,
        "action": event, "message": f"合规结论 {compliance}（命中 {hits}）",
        "compliance": compliance, "hits": hits, "assignee": assignee,
    }


def _extract_text(task_type: str, result) -> str:
    """把结构化结果压平成一段文本，供合规双通道检查。"""
    if task_type == "faq_expansion":
        parts: list[str] = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    parts.append(str(item.get("question", "")))
                    parts.append(str(item.get("answer", "")))
        return "\n".join(parts)
    if isinstance(result, dict):
        parts = []
        for val in result.values():
            if isinstance(val, list):
                parts.extend(str(x) for x in val)
            else:
                parts.append(str(val))
        return "\n".join(parts)
    return str(result)
