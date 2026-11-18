"""数据库基础设施：SQLite WAL 模式 + SQLAlchemy engine/session 工厂。"""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.repositories.orm import Base


def _attach_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def build_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith("sqlite"):
        _attach_sqlite_pragmas(engine)
    return engine


class Database:
    """封装 engine 与 session 工厂；切换 PostgreSQL 仅需更换 database_url。"""

    def __init__(self, database_url: str) -> None:
        self._ensure_sqlite_parent_dir(database_url)
        self.engine = build_engine(database_url)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    @staticmethod
    def _ensure_sqlite_parent_dir(database_url: str) -> None:
        """SQLite 不会自动创建父目录：文件数据库初始化前确保目录存在。"""
        if not database_url.startswith("sqlite"):
            return
        if ":memory:" in database_url or database_url == "sqlite://":
            return
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            return
        path = database_url[len(prefix):]
        if not path:
            return
        db_path = Path(path)
        if db_path.parent and str(db_path.parent) not in (".", "") and not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self._session_factory()

    def journal_mode(self) -> str:
        with self.engine.connect() as conn:
            return str(conn.exec_driver_sql("PRAGMA journal_mode").scalar())


_database: Database | None = None


def get_database() -> Database:
    """默认数据库单例（基于 settings.database_url，惰性初始化）。"""
    global _database
    if _database is None:
        from app.config import settings

        _database = Database(settings.database_url)
    return _database


def reset_database_singleton() -> None:
    global _database
    _database = None