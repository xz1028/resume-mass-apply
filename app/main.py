"""应用入口：FastAPI 应用工厂。

单命令启动：uvicorn app.main:app --host 0.0.0.0 --port 8000
启动时初始化数据库、注册平台适配器、启动调度器；挂载 /metrics 与统一错误处理。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    ai,
    blacklist,
    browser_component,
    demo_mode,
    delivery_records,
    delivery_tasks,
    platform_access,
    platforms,
    positions,
    profile,
    recommendations,
    resumes,
)
from app.api.v1.errors import AppError
from app.infra.database import get_database
from app.infra.logging import configure_logging, get_logger
from app.infra.metrics import render_metrics
from app.infra.scheduler import start_scheduler, stop_scheduler
from app.platforms.mock_adapter import MockAdapter
from app.platforms.registry import get_registry

logger = get_logger("main")

DEFAULT_PARTIAL_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_default_resume "
    "ON resume_profiles(user_id) WHERE is_default = 1"
)

AI_ACTIVE_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_config_active "
    "ON ai_model_configs(is_active) WHERE is_active = 1"
)

JD_COLUMNS = ("jd_text", "jd_fetched_at")


def _ensure_position_jd_columns(conn) -> None:
    """存量库轻量迁移：job_positions 缺 JD 列则 ALTER 补列（可空，旧行零影响）。"""
    rows = conn.exec_driver_sql("PRAGMA table_info(job_positions)").fetchall()
    existing = {row[1] for row in rows}
    if "jd_text" not in existing:
        conn.exec_driver_sql("ALTER TABLE job_positions ADD COLUMN jd_text TEXT")
    if "jd_fetched_at" not in existing:
        conn.exec_driver_sql("ALTER TABLE job_positions ADD COLUMN jd_fetched_at DATETIME")


def _init_storage() -> None:
    """建表 + 数据库层唯一默认约束（部分唯一索引）。"""
    database = get_database()
    database.create_all()
    try:
        with database.engine.connect() as conn:
            conn.exec_driver_sql(DEFAULT_PARTIAL_INDEX)
            conn.exec_driver_sql(AI_ACTIVE_UNIQUE_INDEX)
            _ensure_position_jd_columns(conn)
            conn.commit()
    except Exception:  # noqa: BLE001
        logger.warning("partial_index_skipped", index="ux_default_resume")


def _register_default_platforms() -> None:
    """注册内置模拟平台（新增真实平台仅需实现适配器并在此注册）。"""
    registry = get_registry()
    if registry.get("mock_platform") is None:
        registry.register(MockAdapter(demo_data=True), name="模拟招聘平台")
        logger.info("default_platform_registered", platform_id="mock_platform")


def create_app(*, with_scheduler: bool = True) -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _init_storage()
        _register_default_platforms()
        from app.infra.database import get_database
        from app.real_platform.access.bootstrap import (
            bootstrap_real_platforms,
            shutdown_real_platforms,
        )

        bootstrap_session = get_database().session()
        try:
            bootstrap_real_platforms(bootstrap_session, get_registry())
        finally:
            bootstrap_session.close()
        # 演示模式一键开箱（tasks 2.4）：平台注册完成后、调度器之前注入；
        # demo_mode 默认 off 即时返回（142 项既有测试零影响）
        from app.services.demo_mode_service import DemoModeService

        demo_session = get_database().session()
        try:
            DemoModeService(demo_session).bootstrap()
        except Exception:  # noqa: BLE001
            logger.exception("demo_mode_bootstrap_failed")
        finally:
            demo_session.close()
        if with_scheduler:
            start_scheduler()
        yield
        shutdown_real_platforms()
        if with_scheduler:
            stop_scheduler()

    app = FastAPI(title="就业海投简历系统", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    for router in (
        resumes.router,
        profile.router,
        blacklist.router,
        positions.router,
        recommendations.router,
        delivery_tasks.router,
        delivery_records.router,
        platforms.router,
        platform_access.router,
        ai.router,
        demo_mode.router,
        browser_component.router,
    ):
        app.include_router(router)

    @app.get("/metrics")
    def metrics() -> Response:
        data, content_type = render_metrics()
        return Response(content=data, media_type=content_type)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # 静态资源挂载：必须在全部 API 路由注册之后（先挂载会遮蔽 /api/v1、/health、/metrics）
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()