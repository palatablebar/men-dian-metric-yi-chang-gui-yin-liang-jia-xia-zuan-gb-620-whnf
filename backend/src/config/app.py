"""FastAPI 装配：中间件顺序、异常处理、路由挂载、启动钩子。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.database import engine, wait_for_db
from src.config.settings import settings
from src.middlewares.audit_logger import AuditMiddleware
from src.middlewares.auth import AuthMiddleware
from src.middlewares.error_handler import register_exception_handlers
from src.middlewares.rate_limit import RateLimitMiddleware
from src.routes import api_router

logger = logging.getLogger(f"{settings.app_name}.app")


def _bootstrap_database() -> None:
    from src.models import Base  # noqa: WPS433 - 延迟导入避免循环

    wait_for_db()
    Base.metadata.create_all(bind=engine)
    _ensure_added_columns()


# create_all 不会给已有表补列；升级旧数据卷时用轻量补列保证向后兼容。
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "runs": [("calendar_version", "INTEGER NOT NULL DEFAULT 0")],
    "anomalies": [
        ("calendar_version", "INTEGER NOT NULL DEFAULT 0"),
        ("invalidated", "BOOLEAN NOT NULL DEFAULT 0"),
        ("invalidated_reason", "VARCHAR(60) NULL"),
        ("invalidated_by_version", "INTEGER NULL"),
    ],
    "attributions": [
        ("calendar_version", "INTEGER NOT NULL DEFAULT 0"),
        ("sample_key", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("updated_at", "DATETIME NULL"),
    ],
    "reports": [
        ("calendar_version", "INTEGER NOT NULL DEFAULT 0"),
        ("invalidated", "BOOLEAN NOT NULL DEFAULT 0"),
        ("invalidated_reason", "VARCHAR(60) NULL"),
        ("invalidated_by_version", "INTEGER NULL"),
        ("superseded_by", "INTEGER NULL"),
    ],
}


def _ensure_added_columns() -> None:
    from sqlalchemy import inspect, text

    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        with engine.begin() as conn:
            for table, columns in _ADDED_COLUMNS.items():
                if table not in existing_tables:
                    continue
                present = {column["name"] for column in inspector.get_columns(table)}
                for name, ddl in columns:
                    if name not in present:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    except Exception as exc:  # noqa: BLE001 - 补列失败不应阻塞启动（新库无需补列）
        logger.warning("[BOOTSTRAP] ensure columns skipped: %s", exc)


def _run_seed_once() -> None:
    if not settings.seed_demo:
        return
    try:
        from scripts.seed_demo import seed_all

        seed_all()
    except Exception as exc:  # noqa: BLE001 - 启动阶段不阻塞
        logger.warning("[SEED_DEMO] seed failed (ignored): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap_database()
    _run_seed_once()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_title, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuthMiddleware)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RateLimitMiddleware)
    register_exception_handlers(app)

    app.include_router(api_router, prefix="/api")
    app.include_router(api_router, include_in_schema=False)
    return app
