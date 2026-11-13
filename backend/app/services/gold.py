"""聚合层管理业务规则：状态流转、字段校验、筛选口径都收在这里。

效果视图（按上游清洗表汇总的完成度/新鲜度/可执行状态）统一走 app.effects，
本服务只负责取数、按筛选条件裁剪与分页，保证列表与导出回执同源。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.effects import (
    STATUS_BLOCKED,
    STATUS_READY,
    build_view_effect,
    parse_as_of,
)
from app.store import store

MODULE = "gold"
REQUIRED_FIELDS = ["视图编号", "上游清洗表", "聚合维度"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用聚合": "已启用", "停用聚合": "已停用"}
NEGATIVE_ACTIONS = ["停用聚合"]

# 效果视图支持的可执行状态筛选词。
EFFECT_STATES = [STATUS_READY, STATUS_BLOCKED, "无法判定"]


def _silver_index() -> dict[str, dict[str, Any]]:
    return {str(row.get("表编号")): row for row in store.rows("silver")}


def _quality_index() -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in store.rows("quality"):
        index.setdefault(str(row.get("监控对象")), []).append(row)
    return index


def _meta_index() -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in store.rows("meta"):
        index.setdefault(str(row.get("对象名称")), []).append(row)
    return index


class GoldService:
    # ----- 既有聚合视图登记列表（保留原调用链） -----
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        layer: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("视图编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if layer:
            rows = [row for row in rows if str(row.get("所属分层", "")) == layer]
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
            return None, f"聚合视图 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于聚合层管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"聚合视图已{action}"

    # ----- 效果视图：按上游清洗表汇总完成度 / 新鲜度 / 可执行状态 -----
    def filter_options(self) -> dict[str, Any]:
        gold_rows = store.rows(MODULE)
        return {
            "layers": sorted({str(row.get("所属分层", "")).strip() for row in gold_rows if row.get("所属分层")}),
            "frequencies": sorted({str(row.get("更新频率", "")).strip() for row in gold_rows if row.get("更新频率")}),
            "states": EFFECT_STATES,
            "statuses": STATUS_ORDER,
        }

    def effect_views(
        self,
        *,
        keyword: str | None = None,
        layer: str | None = None,
        frequency: str | None = None,
        state: str | None = None,
        status: str | None = None,
        as_of: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """实时计算效果视图。无缓存：上游清洗表一变，可查询范围立即跟着变。"""
        moment = as_of or datetime.now()
        silver_index = _silver_index()
        quality_index = _quality_index()
        meta_index = _meta_index()

        effects: list[dict[str, Any]] = []
        for gold_row in store.rows(MODULE):
            # 展示口径必须与当前筛选一致：先按视图级条件过滤，再计算明细。
            if keyword and keyword not in str(gold_row.get("视图编号", "")):
                continue
            if layer and str(gold_row.get("所属分层", "")) != layer:
                continue
            if frequency and str(gold_row.get("更新频率", "")) != frequency:
                continue
            if status and gold_row.get("status") != status:
                continue
            effect = build_view_effect(
                gold_row,
                silver_index=silver_index,
                quality_index=quality_index,
                meta_index=meta_index,
                as_of=moment,
            )
            if state and effect["可执行状态"] != state:
                continue
            effects.append(effect)

        total = len(effects)
        start = max(page - 1, 0) * size
        return effects[start:start + size], total

    def effect_export(self, **filters: Any) -> dict[str, Any]:
        """导出回执与列表同源：同一个 effect_views，同一套筛选与口径。"""
        as_of = filters.get("as_of") or datetime.now()
        filters.pop("page", None)
        filters.pop("size", None)
        items, total = self.effect_views(page=1, size=10000, **filters)
        # 基准时刻单独成列，筛选条件只回显业务过滤项，避免把 datetime 对象混进回执。
        applied = {
            key: value
            for key, value in filters.items()
            if key != "as_of" and value not in (None, "")
        }
        return {
            "module": "gold_effect",
            "口径": "按上游清洗表汇总的聚合效果视图，与页面列表同源实时计算",
            "筛选条件": applied,
            "基准时刻": as_of.strftime("%Y-%m-%d %H:%M:%S"),
            "total": total,
            "items": items,
        }

    def effect_summary(self, **filters: Any) -> dict[str, int]:
        """统计卡片同样基于当前筛选口径实时汇总。"""
        filters.pop("page", None)
        filters.pop("size", None)
        items, _ = self.effect_views(page=1, size=10000, **filters)
        return {
            "视图总数": len(items),
            "可执行视图": sum(1 for item in items if item["可执行状态"] == STATUS_READY),
            "不可执行视图": sum(1 for item in items if item["可执行状态"] == STATUS_BLOCKED),
            "无法判定视图": sum(1 for item in items if item["可执行状态"] not in (STATUS_READY, STATUS_BLOCKED)),
        }
