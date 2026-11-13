"""数据湖仓一体管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.store import store

app = FastAPI(title="数据湖仓一体管理平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _order_static_routes_first(router) -> None:
    """把静态路径排到带路径参数的路由之前。

    各模块按“/{entry_id} 在前、/export 在后”的顺序声明，FastAPI 按声明顺序匹配，
    导致 /export 被 /{entry_id} 截获并报整数解析错误。这里用稳定排序把无参静态
    路径前置（组内保持原顺序），既修复 /export，又不影响 {entry_id} 的匹配与校验。
    必须在首次请求构建路由缓存之前完成（应用启动阶段，满足该条件）。
    """
    router.routes.sort(key=lambda route: "{" in getattr(route, "path", ""))


for module in ROUTERS:
    _order_static_routes_first(module.router)
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.post("/api/reset")
def reset_demo_data() -> dict[str, object]:
    """重置内存仓库到种子数据，供演示与验收测试重复运行（仅演示环境使用）。"""
    store.reset()
    return {"ok": True, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()
