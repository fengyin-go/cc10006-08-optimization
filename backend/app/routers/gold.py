"""聚合层管理接口：维护聚合视图，并提供按上游清洗表汇总的效果视图。

效果视图相关接口（/effects、/effects/filters、/effects/export）共用
GoldService.effect_views 同一个计算入口，保证页面列表与导出回执同源；
上游清洗表的完成度变化实时驱动可查询范围，不存在两套相反结论。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.effects import EffectTimeError, parse_as_of
from app.schemas import ActionResult, EntryPayload, PageResult, action_of
from app.services.gold import EFFECT_STATES, GoldService

router = APIRouter(prefix="/api/gold", tags=["聚合层管理"])

service = GoldService()

LIST_FIELDS = ["视图编号", "上游清洗表", "聚合维度", "度量字段", "聚合函数", "物化策略", "更新频率", "数据新鲜度"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


def _resolve_as_of(raw: str | None):
    try:
        return parse_as_of(raw)
    except EffectTimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按视图编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    layer: str | None = Query(default=None, description="按所属分层过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按视图编号、状态与所属分层过滤聚合层管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, layer=layer, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/effects/filters")
def effect_filters() -> dict[str, Any]:
    """效果视图的筛选项：所属分层、更新频率、可执行状态随数据动态返回。"""
    return service.filter_options()


@router.get("/effects", response_model=PageResult[dict])
def effect_views(
    keyword: str | None = Query(default=None, description="按视图编号检索"),
    layer: str | None = Query(default=None, description="所属分层：DWD/DWS/ADS"),
    frequency: str | None = Query(default=None, description="更新频率：每小时/每日/每周"),
    state: str | None = Query(default=None, description="可执行状态：可执行/不可执行/无法判定"),
    status: str | None = Query(default=None, description="视图自身状态：草稿/待校验/已启用/已停用"),
    as_of: str | None = Query(default=None, description="效果判定基准时刻，默认当前时刻；非法值返回 400"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按上游清洗表汇总的聚合效果视图：完成度、更新频率、新鲜度与可执行状态。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if state and state not in EFFECT_STATES:
        raise HTTPException(status_code=400, detail=f"可执行状态「{state}」不在允许范围：{'、'.join(EFFECT_STATES)}")
    moment = _resolve_as_of(as_of)
    items, total = service.effect_views(
        keyword=keyword,
        layer=layer,
        frequency=frequency,
        state=state,
        status=status,
        as_of=moment,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/effects/summary")
def effect_summary(
    keyword: str | None = None,
    layer: str | None = None,
    frequency: str | None = None,
    state: str | None = None,
    status: str | None = None,
    as_of: str | None = None,
) -> dict[str, int]:
    """效果视图统计卡片：与列表同一套筛选口径，随上游状态实时变化。"""
    if state and state not in EFFECT_STATES:
        raise HTTPException(status_code=400, detail=f"可执行状态「{state}」不在允许范围：{'、'.join(EFFECT_STATES)}")
    moment = _resolve_as_of(as_of)
    return service.effect_summary(
        keyword=keyword, layer=layer, frequency=frequency, state=state, status=status, as_of=moment
    )


@router.get("/effects/export")
def effect_export(
    keyword: str | None = None,
    layer: str | None = None,
    frequency: str | None = None,
    state: str | None = None,
    status: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """导出效果视图回执：与页面列表同源，回显筛选条件与基准时刻。"""
    if state and state not in EFFECT_STATES:
        raise HTTPException(status_code=400, detail=f"可执行状态「{state}」不在允许范围：{'、'.join(EFFECT_STATES)}")
    moment = _resolve_as_of(as_of)
    return service.effect_export(
        keyword=keyword, layer=layer, frequency=frequency, state=state, status=status, as_of=moment
    )


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条聚合视图明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"聚合视图 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条聚合视图，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="聚合视图已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条聚合视图执行提交校验、启用聚合、停用聚合；不允许的动作会被拦下并说明原因。"""
    action = action_of(payload)
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    status: str | None = None,
    layer: str | None = None,
) -> dict[str, Any]:
    """导出聚合层登记清单：与列表接口同口径，回显当前过滤条件。"""
    items, total = service.list_entries(keyword=keyword, status=status, layer=layer, page=1, size=10000)
    return {
        "module": "gold",
        "筛选条件": {key: value for key, value in {
            "keyword": keyword, "status": status, "layer": layer
        }.items() if value},
        "total": total,
        "items": items,
    }
