"""测试基础设施：独立数据库/加密/限流/注册表环境 + FastAPI TestClient。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.infra.crypto as crypto_module
import app.infra.database as database_module
import app.infra.rate_limiter as rate_limiter_module
import app.platforms.registry as registry_module
import app.services.delivery_service as delivery_service_module
import app.services.job_service as job_service_module
import app.services.matching_service as matching_service_module
from app.config import settings
from app.infra.crypto import CryptoService
from app.infra.database import Database
from app.infra.rate_limiter import RateLimiterRegistry
from app.platforms.mock_adapter import MockAdapter
from app.platforms.registry import AdapterRegistry

PARTIAL_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_default_resume "
    "ON resume_profiles(user_id) WHERE is_default = 1"
)


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    """独立运行环境：临时数据库、密钥、限流器、注册表与存储目录。"""
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_all()
    with database.engine.connect() as conn:
        conn.exec_driver_sql(PARTIAL_INDEX)
        conn.commit()
    monkeypatch.setattr(database_module, "_database", database)

    crypto = CryptoService(tmp_path / "secret.key")
    monkeypatch.setattr(crypto_module, "_crypto", crypto)

    rate_limiters = RateLimiterRegistry({"mock_platform": 100000.0})
    monkeypatch.setattr(rate_limiter_module, "_rate_limiters", rate_limiters)

    registry = AdapterRegistry()
    mock = MockAdapter()
    registry.register(mock, name="模拟招聘平台")
    monkeypatch.setattr(registry_module, "_registry", registry)

    monkeypatch.setattr(settings, "resume_storage_dir", tmp_path / "resumes")
    monkeypatch.setattr(matching_service_module, "_cache", {})
    monkeypatch.setattr(delivery_service_module, "_cancel_flags", set())
    monkeypatch.setattr(job_service_module, "_stale_platforms", {})

    return SimpleNamespace(
        database=database,
        crypto=crypto,
        registry=registry,
        mock=mock,
        tmp_path=tmp_path,
    )


@pytest.fixture
def client(test_env):
    """不触发 lifespan 的 TestClient（环境由 fixture 准备，避免后台调度器）。"""
    from app.main import create_app

    app = create_app(with_scheduler=False)
    return TestClient(app)


@pytest.fixture
def reset_notifier(monkeypatch):
    """每个测试使用独立的默认通知客户端与空暂存队列。"""
    import app.infra.notifier as notifier_module
    from app.infra.notifier import LoggingNotificationClient

    monkeypatch.setattr(notifier_module, "_notifier", LoggingNotificationClient())
    monkeypatch.setattr(notifier_module, "_pending_events", [])
    return notifier_module