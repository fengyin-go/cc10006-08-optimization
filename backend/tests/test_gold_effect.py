"""聚合效果视图端到端验收用例。

只依赖标准库（urllib + json），不引入 pytest/httpx，和项目 requirements.txt 保持一致。
先在本地启动后端（uvicorn app.main:app --port 8000），再执行：

    python tests/test_gold_effect.py

脚本会通过真实 HTTP 调用验证：上午批次延迟/正常两张清洗表的效果、分层与状态筛选、
列表与导出同源、上游状态实时驱动可查询范围、非法时间不显示成健康、冲突阈值以更新
频率为准，以及质量指标/元数据版本的直接定位。
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# 允许直接 `python tests/test_gold_effect.py` 运行：把后端根目录加入模块搜索路径。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000"


def call(path: str, method: str = "GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def effects(**params):
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return call(f"/api/gold/effects?{query}&size=100")


def view_by_code(items, code):
    return next(v for v in items if v["视图编号"] == code)


def upstream(view, code):
    return next(u for u in view["upstreams"] if u["清洗表编号"] == code)


def main() -> None:
    # 先重置内存仓库，保证测试可重复执行、结论不依赖上一次运行残留状态。
    reset_status, _ = call("/api/reset", "POST")
    assert reset_status == 200, "无法重置演示数据，请确认后端已启动"

    passed: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        assert cond, f"{name} 失败：{detail}"
        passed.append(name)

    # 1. 上午批次：一张延迟 20 分钟、一张正常完成。
    status, payload = effects()
    check("效果接口可用", status == 200)
    v1 = view_by_code(payload["items"], "GOLD-0001")
    u1, u2 = upstream(v1, "SILV-0001"), upstream(v1, "SILV-0002")
    check("延迟表完成度 60%", u1["完成度"] == 60)
    check("延迟表状态未完成", u1["上游状态"] == "未完成")
    check("延迟表含更新频率", u1["更新频率"] == "每日")
    check("延迟表含数据新鲜度", "更新于" in u1["数据新鲜度"])
    check("正常表完成度 100%", u2["完成度"] == 100 and u2["上游状态"] == "健康")
    check("视图级不可执行", v1["可执行状态"] == "不可执行")
    check("可执行视图可查询", view_by_code(effects()[1]["items"], "GOLD-0002")["可执行状态"] == "可执行")

    # 2. 质量指标与元数据版本可直接定位。
    check("挂载质量指标", u1["质量指标"][0]["指标编号"] == "QUAL-0001")
    check("挂载元数据版本", u1["元数据版本"][0]["属性值"] == "v3")
    check("质量页定位", call("/api/quality?monitor_object=SILV-0001")[1]["total"] == 1)
    check("元数据页定位", call("/api/meta?object_name=SILV-0001")[1]["total"] == 1)

    # 3. 切换所属分层只显示符合条件的结果。
    check("ADS 分层", {v["视图编号"] for v in effects(layer="ADS")[1]["items"]}
          == {"GOLD-0001", "GOLD-0003", "GOLD-0004"})
    check("可执行状态筛选", {v["视图编号"] for v in effects(state="可执行")[1]["items"]} == {"GOLD-0002"})
    check("非法状态 400", effects(state="非法")[0] == 400)

    # 4. 列表与导出回执同源，结论一致。
    listed = effects(layer="ADS", state="不可执行")[1]
    export_query = urllib.parse.urlencode({"layer": "ADS", "state": "不可执行"})
    exported = call(f"/api/gold/effects/export?{export_query}")[1]
    check("导出回显筛选", exported["筛选条件"]["layer"] == "ADS")
    check("条数一致", exported["total"] == listed["total"])
    map_list = {v["视图编号"]: (v["可执行状态"], v["最低完成度"]) for v in listed["items"]}
    map_export = {v["视图编号"]: (v["可执行状态"], v["最低完成度"]) for v in exported["items"]}
    check("逐条结论一致", map_list == map_export)

    # 5. 上游状态变化立即驱动可查询范围（无缓存）。
    check("变化前不可执行", view_by_code(effects(keyword="GOLD-0001")[1]["items"], "GOLD-0001")["可执行状态"] == "不可执行")
    status, resp = call("/api/silver/1/actions", "POST", {"action": "模拟批次完成"})
    check("模拟完成生效", status == 200 and resp["ok"] is True, str(resp))
    after = view_by_code(effects(keyword="GOLD-0001")[1]["items"], "GOLD-0001")
    check("完成后立即可执行（无旧结论残留）", after["可执行状态"] == "可执行", after["可执行状态"])
    check("导出同步翻转", view_by_code(call("/api/gold/effects/export?keyword=GOLD-0001")[1]["items"], "GOLD-0001")["可执行状态"] == "可执行")
    call("/api/silver/1/actions", "POST", {"action": "模拟批次延迟"})
    check("再延迟立即恢复不可执行", view_by_code(effects(keyword="GOLD-0001")[1]["items"], "GOLD-0001")["可执行状态"] == "不可执行")

    # 6. 非法时间范围不能显示成健康结果。
    call("/api/silver/4/actions", "POST", {"action": "模拟时间异常"})
    v3 = view_by_code(effects(keyword="GOLD-0003")[1]["items"], "GOLD-0003")
    check("未来时间判时间异常", v3["视图状态"] == "时间异常" and v3["可执行状态"] == "不可执行")
    check("非法基准时刻 400", effects(as_of="not-a-time")[0] == 400)

    # 7. 冲突阈值以更新频率为准：同表同数据，不同频率视图结论不同。
    from app.effects import build_upstream_effect
    from app.store import store

    silver_row = next(r for r in store.rows("silver") if r["表编号"] == "SILV-0003")
    as_of = datetime.now() + timedelta(hours=3)
    hourly = build_upstream_effect(silver_row, view_frequency="每小时", as_of=as_of, silver_code="SILV-0003")
    daily = build_upstream_effect(silver_row, view_frequency="每日", as_of=as_of, silver_code="SILV-0003")
    check("每小时口径超阈值不可执行", hourly["可执行"] is False and hourly["上游状态"] == "新鲜度超标")
    check("每日口径仍健康", daily["可执行"] is True and daily["上游状态"] == "健康")

    # 8. 登记清单导出不被 /{entry_id} 截获（静态路由优先），参数校验仍然有效。
    export_status, export_body = call("/api/gold/export")
    check("登记清单导出可用", export_status == 200 and export_body.get("module") == "gold")
    check("效果导出可用", call("/api/gold/effects/export")[0] == 200)
    check("整数参数路由仍可用", call("/api/gold/1")[0] == 200)
    check("非整数参数仍 422", call("/api/gold/abc")[0] == 422)

    # 9. 动作接口同时兼容扁平 {action} 与 {values:{action}} 两种提交结构。
    flat_status, flat = call("/api/bronze/1/actions", "POST", {"action": "提交校验"})
    check("扁平动作提交生效", flat_status == 200 and flat["ok"] is True)
    wrapped_status, wrapped = call("/api/catalog/1/actions", "POST", {"values": {"action": "提交审核"}})
    check("包裹动作提交生效", wrapped_status == 200 and wrapped["ok"] is True)
    invalid_status, invalid = call("/api/bronze/1/actions", "POST", {"action": "不存在的动作"})
    check("非法动作被拦截", invalid_status == 200 and invalid["ok"] is False)

    print(f"全部 {len(passed)} 项验收通过：")
    for name in passed:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
