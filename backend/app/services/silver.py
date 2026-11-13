"""清洗层管理业务规则：状态流转、字段校验与筛选口径都收在这里。

除了既有生命周期动作外，增加批次模拟动作（模拟延迟、模拟完成、模拟时间异常），
直接改写完成度与时间字段。聚合效果视图实时读取这些字段、不做缓存，
因此上游状态一变，聚合视图的可查询范围与可执行结论立即联动。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

MODULE = "silver"
REQUIRED_FIELDS = ["表编号", "上游原始表", "清洗脚本"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用清洗": "已启用", "停用清洗": "已停用"}
NEGATIVE_ACTIONS = ["停用清洗"]

# 批次模拟动作：不动生命周期状态，只改批次完成度/时间，便于值班联调。
SIMULATE_ACTIONS = ["模拟批次延迟", "模拟批次完成", "模拟时间异常"]
SIMULATE_DELAY_COMPLETION = 60
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class SilverService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("表编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"清洗表 {entry_id} 不存在或已归档"
        if action in SIMULATE_ACTIONS:
            return self._simulate(entry, action)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于清洗层管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"清洗表已{action}"

    def _simulate(self, entry: dict[str, Any], action: str) -> tuple[dict[str, Any], str]:
        now = datetime.now()
        entry.setdefault("计划完成时间", (now - timedelta(minutes=20)).strftime(TIME_FORMAT))
        if action == "模拟批次延迟":
            # 上午批次延迟 20 分钟仍未跑完：完成度停在 60%，最近完成时间还是昨天。
            entry["完成度"] = SIMULATE_DELAY_COMPLETION
            entry["批次状态"] = "延迟"
            entry["最近完成时间"] = (now - timedelta(days=1)).strftime(TIME_FORMAT)
            entry["abnormal"] = True
            message = "已模拟批次延迟：完成度 60%，最近完成时间回退到昨日"
        elif action == "模拟批次完成":
            # 正常完成：完成度 100%，最近完成时间落在阈值之内。
            entry["完成度"] = 100
            entry["批次状态"] = "正常"
            entry["最近完成时间"] = (now - timedelta(minutes=5)).strftime(TIME_FORMAT)
            entry["abnormal"] = False
            message = "已模拟批次正常完成：完成度 100%，最近完成时间为 5 分钟前"
        else:
            # 非法时间范围：最近完成时间落在未来，效果视图必须判时间异常而非健康。
            entry["完成度"] = 100
            entry["批次状态"] = "时间异常"
            entry["最近完成时间"] = (now + timedelta(days=1)).strftime(TIME_FORMAT)
            entry["abnormal"] = True
            message = "已模拟时间异常：最近完成时间落在未来，聚合效果视图将判为不可执行"
        return entry, message
