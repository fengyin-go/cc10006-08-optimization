"""聚合效果口径引擎：上游完成度、数据新鲜度与可执行状态的唯一计算来源。

设计约束（对应需求里的硬性口径）：

1. 列表与导出回执必须同源 —— 路由层只能调用本模块的 build_effect_view，
   不允许各自再算一遍，避免同一份完成度在两个视图给出相反结论。
2. 冲突阈值以更新频率为准 —— 同一张清洗表被不同频率的聚合视图引用时，
   新鲜度阈值取“当前聚合视图”的更新频率，而不是清洗表自己的调度周期。
3. 非法时间范围不能显示成健康结果 —— 最近完成时间无法解析、落在基准时刻
   之后（未来数据）或早于下限，一律判为“时间异常”，不得落入可执行。
4. 上游状态变化立即驱动可查询范围 —— 所有结果实时从内存仓库现算，
   不做缓存；清洗表完成度一改，下一次查询就是新结论。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# 可执行 / 不可执行的统一状态词，前端据此着色与筛选。
STATUS_READY = "可执行"
STATUS_BLOCKED = "不可执行"
STATUS_UNKNOWN = "无法判定"

# 上游明细级状态（粒度更细，汇总视图状态取其中最差者）。
UP_MISSING = "上游缺失"
UP_INCOMPLETE = "未完成"
UP_STALE = "新鲜度超标"
UP_TIME_INVALID = "时间异常"
UP_FREQUENCY_UNKNOWN = "频率未配置"
UP_HEALTHY = "健康"

# 状态严重度排序：数值越大越差，聚合视图取最差状态。
STATUS_SEVERITY = {
    UP_HEALTHY: 0,
    UP_FREQUENCY_UNKNOWN: 1,
    UP_STALE: 2,
    UP_INCOMPLETE: 3,
    UP_TIME_INVALID: 4,
    UP_MISSING: 5,
}

# 更新频率 -> 新鲜度冲突阈值（分钟）。阈值冲突时以聚合视图的更新频率为准。
FREQUENCY_THRESHOLD_MINUTES: dict[str, int] = {
    "每小时": 90,
    "每日": 1440,       # 24 小时
    "每周": 10080,      # 7 天
    "每月": 43200,      # 30 天
}

# 早于该下限的时间戳视为非法（演示系统的合理下界）。
_MIN_VALID_TIME = datetime(2000, 1, 1)
_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


class EffectTimeError(ValueError):
    """基准时刻或业务时间字段无法解析时抛出，路由层转成 400。"""


def parse_moment(value: Any, *, field: str = "时间") -> datetime | None:
    """宽松解析时间字段；空值返回 None，无法解析抛出 EffectTimeError。"""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise EffectTimeError(f"{field}「{text}」无法解析为合法时间")


def parse_as_of(value: str | None) -> datetime:
    """解析查询参数 as_of；缺省取当前时刻，非法值显式报错而非静默健康。"""
    if not value:
        return datetime.now()
    try:
        return parse_moment(value, field="基准时刻")
    except EffectTimeError as exc:
        raise EffectTimeError(f"基准时刻参数 as_of 非法：{exc}") from exc


def _format_minutes(minutes: float) -> str:
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, remain = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} 小时{remain} 分钟" if remain else f"{hours} 小时"
    days, hour_remain = divmod(hours, 24)
    return f"{days} 天{hour_remain} 小时" if hour_remain else f"{days} 天"


def _completion(row: dict[str, Any] | None) -> int | None:
    if not row:
        return None
    try:
        value = int(float(row.get("完成度")))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0, min(100, value))


def build_upstream_effect(
    silver_row: dict[str, Any] | None,
    *,
    view_frequency: str,
    as_of: datetime,
    silver_code: str = "",
) -> dict[str, Any]:
    """计算单张上游清洗表对某个聚合视图的效果明细。

    阈值取 ``view_frequency``（聚合视图更新频率），保证同一清洗表在不同
    频率视图下按各自口径判定，冲突时频率说了算。
    """
    base: dict[str, Any] = {
        "清洗表编号": silver_code,
        "清洗表名称": (silver_row or {}).get("上游原始表", ""),
        "所属分层": (silver_row or {}).get("所属分层", ""),
        "更新频率": (silver_row or {}).get("更新频率", "") or view_frequency,
        "视图更新频率": view_frequency,
        "完成度": None,
        "计划完成时间": (silver_row or {}).get("计划完成时间", ""),
        "最近完成时间": (silver_row or {}).get("最近完成时间", ""),
        "新鲜度分钟": None,
        "数据新鲜度": "—",
        "延迟分钟": None,
        "批次延迟": "—",
        "上游状态": UP_MISSING,
        "可执行": False,
        "不可执行原因": "上游清洗表不存在或已下线",
        "silver_id": (silver_row or {}).get("id"),
    }
    if silver_row is None:
        return base

    completion = _completion(silver_row)
    base["完成度"] = completion

    plan_at = parse_moment(silver_row.get("计划完成时间"), field="计划完成时间")
    last_at = parse_moment(silver_row.get("最近完成时间"), field="最近完成时间")

    # 延迟口径：已完成批次比“完成时刻 vs 计划时刻”，未完成批次比“当前时刻 vs 计划时刻”。
    if plan_at is not None:
        if completion == 100 and last_at is not None:
            delay = int((last_at - plan_at).total_seconds() // 60)
            if delay > 0:
                base["批次延迟"] = f"延迟 {_format_minutes(delay)}完成"
            elif delay < 0:
                base["批次延迟"] = f"提前 {_format_minutes(-delay)}完成"
            else:
                base["批次延迟"] = "按时完成"
        else:
            delay = int((as_of - plan_at).total_seconds() // 60)
            base["批次延迟"] = f"已超计划 {_format_minutes(max(delay, 0))}仍未完成"
        base["延迟分钟"] = delay

    # 新鲜度口径：相对最近一次完成时间；负值说明时间戳落在未来，属于非法数据。
    if last_at is not None:
        freshness_minutes = int((as_of - last_at).total_seconds() // 60)
        base["新鲜度分钟"] = freshness_minutes
        if freshness_minutes < 0:
            base["数据新鲜度"] = f"时间戳晚于当前 {_format_minutes(-freshness_minutes)}（未来数据）"
        else:
            base["数据新鲜度"] = f"更新于 {_format_minutes(freshness_minutes)}前"

    threshold = FREQUENCY_THRESHOLD_MINUTES.get(view_frequency)

    # 1) 非法时间范围：缺失、未来数据、过早数据 —— 一律时间异常，绝不健康。
    time_invalid = (
        last_at is None
        or last_at > as_of
        or last_at < _MIN_VALID_TIME
        or (plan_at is not None and (plan_at < _MIN_VALID_TIME or plan_at > as_of + timedelta(days=3650)))
    )
    if time_invalid:
        reason = "最近完成时间缺失或落在非法时间范围（含未来时间）"
        base.update(上游状态=UP_TIME_INVALID, 不可执行原因=reason)
        return base

    # 2) 完成度未达 100%：本批次尚未跑完。
    if completion is None or completion < 100:
        base.update(
            上游状态=UP_INCOMPLETE,
            不可执行原因=f"本批次完成度 {completion if completion is not None else '未知'}%，尚未完成",
        )
        return base

    # 3) 阈值冲突以更新频率为准；频率未配置时不给健康结论。
    if threshold is None:
        base.update(
            上游状态=UP_FREQUENCY_UNKNOWN,
            不可执行原因=f"更新频率「{view_frequency}」未配置冲突阈值，无法判定新鲜度",
        )
        return base

    # 4) 新鲜度超标。
    if base["新鲜度分钟"] is not None and base["新鲜度分钟"] > threshold:
        base.update(
            上游状态=UP_STALE,
            不可执行原因=(
                f"数据已 {_format_minutes(base['新鲜度分钟'])}未更新，"
                f"超过「{view_frequency}」阈值 {_format_minutes(threshold)}"
            ),
        )
        return base

    base.update(
        上游状态=UP_HEALTHY,
        可执行=True,
        不可执行原因="",
    )
    return base


def split_upstream_codes(raw: Any) -> list[str]:
    """聚合视图的上游清洗表字段允许用逗号/顿号/空白分隔多张表。"""
    if raw is None:
        return []
    tokens = str(raw).replace("、", ",").replace(";", ",").replace("，", ",")
    return [token.strip() for token in tokens.split(",") if token.strip()]


def build_view_effect(
    gold_row: dict[str, Any],
    *,
    silver_index: dict[str, dict[str, Any]],
    quality_index: dict[str, list[dict[str, Any]]],
    meta_index: dict[str, list[dict[str, Any]]],
    as_of: datetime,
) -> dict[str, Any]:
    """汇总单个聚合视图：逐张上游清洗表算明细，再折叠出视图级可执行状态。"""
    view_frequency = str(gold_row.get("更新频率") or "").strip()
    codes = split_upstream_codes(gold_row.get("上游清洗表"))
    upstreams: list[dict[str, Any]] = []
    for code in codes:
        silver_row = silver_index.get(code)
        effect = build_upstream_effect(
            silver_row, view_frequency=view_frequency, as_of=as_of, silver_code=code
        )
        effect["质量指标"] = [
            {"id": item.get("id"), "指标编号": item.get("指标编号"), "指标类型": item.get("指标类型")}
            for item in quality_index.get(code, [])
        ]
        effect["元数据版本"] = [
            {"id": item.get("id"), "条目编号": item.get("条目编号"), "属性值": item.get("属性值")}
            for item in meta_index.get(code, [])
        ]
        upstreams.append(effect)

    if upstreams:
        worst = max(upstreams, key=lambda item: STATUS_SEVERITY.get(item["上游状态"], 99))
        all_ready = all(item["可执行"] for item in upstreams)
        view_state = STATUS_READY if all_ready else STATUS_BLOCKED
        reason = "" if all_ready else worst["不可执行原因"]
        completions = [item["完成度"] for item in upstreams if item["完成度"] is not None]
        min_completion = min(completions) if completions else None
        avg_completion = round(sum(completions) / len(completions)) if completions else None
    else:
        worst = {"上游状态": UP_MISSING}
        view_state = STATUS_UNKNOWN
        reason = "未配置上游清洗表"
        min_completion = avg_completion = None

    return {
        "id": gold_row.get("id"),
        "视图编号": gold_row.get("视图编号"),
        "所属分层": gold_row.get("所属分层", ""),
        "聚合维度": gold_row.get("聚合维度", ""),
        "更新频率": view_frequency,
        "物化策略": gold_row.get("物化策略", ""),
        "status": gold_row.get("status"),
        "最低完成度": min_completion,
        "平均完成度": avg_completion,
        "可执行状态": view_state,
        "视图状态": worst["上游状态"],
        "不可执行原因": reason,
        "upstreams": upstreams,
    }
