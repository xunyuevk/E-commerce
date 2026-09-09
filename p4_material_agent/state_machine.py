"""P4 素材任务状态机 —— 自写显式状态机（面试重点：对比 LangGraph）。

为什么自写状态机而非 LangGraph：
  1. 状态少且固定：8 个状态 + 9 个事件，一张 dict 即可完整枚举全部合法迁移，
     无需图编译 / checkpoint / 运行时调度这些额外机制；
  2. 可审计、可打断：每个迁移都是显式 (state, event) -> new_state 键值对，
     非法迁移立刻抛 ValueError（并说明理由），HITL 的 human_review 阶段天然"停住"等外部事件；
  3. 避免框架黑盒与额外依赖：LangGraph 引入的图执行语义对"审核流"这类线性为主、分支有限的
     场景属于过度设计，调试与解释成本反而更高。

演进话术：若未来任务图出现并行分支、超时重试、子图编排等复杂度，再评估 LangGraph / Temporal，
当前需求下自写状态机是最小、最可解释的实现。
"""
from __future__ import annotations

# 状态集合（8 个）
STATES: tuple[str, ...] = (
    "draft",
    "generating",
    "compliance_check",
    "human_review",
    "approved",
    "rejected",
    "published",
    "failed",
)

# 事件集合（9 个）
EVENTS: tuple[str, ...] = (
    "start",
    "generated",
    "compliance_pass",
    "compliance_review",
    "compliance_fail",
    "approve",
    "reject",
    "publish",
    "error",
)

# 终态：对"自动推进"而言不再继续；approved 仍需外部显式 publish 动作才会离开。
TERMINAL_STATES: frozenset[str] = frozenset({"approved", "rejected", "published", "failed"})

# 显式声明所有合法迁移：(当前状态, 事件) -> 下一状态
TRANSITIONS: dict[tuple[str, str], str] = {
    # 创建 → 生成
    ("draft", "start"): "generating",
    # 生成完成 / 生成异常
    ("generating", "generated"): "compliance_check",
    ("generating", "error"): "failed",
    # 合规双通道结论：pass/review 都进入人工审核，fail 直接拒绝
    ("compliance_check", "compliance_pass"): "human_review",
    ("compliance_check", "compliance_review"): "human_review",
    ("compliance_check", "compliance_fail"): "rejected",
    ("compliance_check", "error"): "failed",
    # 人工审核（HITL）
    ("human_review", "approve"): "approved",
    ("human_review", "reject"): "rejected",
    ("human_review", "error"): "failed",
    # 发布
    ("approved", "publish"): "published",
    ("approved", "error"): "failed",
}


def transition(state: str, event: str) -> str:
    """执行一次状态迁移；非法迁移抛 ValueError（并说明理由）。"""
    if state not in STATES:
        raise ValueError(f"非法状态 {state!r}；合法状态：{', '.join(STATES)}")
    if event not in EVENTS:
        raise ValueError(f"非法事件 {event!r}；合法事件：{', '.join(EVENTS)}")
    nxt = TRANSITIONS.get((state, event))
    if nxt is None:
        allowed = ", ".join(ALLOWED_EVENTS(state)) or "（终态，无）"
        raise ValueError(
            f"非法迁移：状态 {state!r} 不接受事件 {event!r}；该状态允许的事件：{allowed}"
        )
    return nxt


def ALLOWED_EVENTS(state: str) -> list[str]:
    """返回某状态当前允许触发的全部事件（未显式声明的迁移一律非法）。

    注：按需求此 API 命名为全大写，视作"状态 → 事件"的只读查询表。
    """
    if state not in STATES:
        raise ValueError(f"非法状态 {state!r}；合法状态：{', '.join(STATES)}")
    return [e for (s, e) in TRANSITIONS if s == state]


def is_terminal(state: str) -> bool:
    """approved / published / rejected / failed 为终态（不再自动推进）。"""
    return state in TERMINAL_STATES
