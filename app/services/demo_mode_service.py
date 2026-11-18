"""演示模式一键开箱服务（spec 5.2 / design 决策 D2/D3/D4）。

红线约束：
- 门控：settings.demo_mode 默认 off——off 时任何调用即时返回，无 IO 无状态写入
- 首启判定四条件：无简历档案 且 无投递记录 且 无平台授权 且 无演示标记
- 幂等：每步先查后插；状态机单一事实源 app_settings(key=demo_mode_state)
- 清除范围四键圈定（决策 D3 零表结构标记）：演示简历行+加密文件、demo_seed_task
  任务与其全部记录、demo_x_ 前缀跨平台演示职位、demo_mode_state 标记
- 已有任何用户简历/记录/授权时禁止注入（真实数据保护）
- 演示记录 platform_record_ref=None：不入状态同步队列
"""

import hashlib
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import DEFAULT_USER_ID, settings
from app.domain.models import (
    DeliveryRecord,
    DeliveryStatus,
    DeliveryTask,
    JobPosition,
    ResumeSnapshot,
    TaskStatus,
)
from app.infra.logging import get_logger
from app.repositories.repos import (
    AuthorizationRepository,
    PositionRepository,
    RecordRepository,
    ResumeRepository,
    SettingRepository,
    TaskRepository,
    new_id,
)

logger = get_logger("demo_mode")

DEMO_STATE_KEY = "demo_mode_state"
DEMO_SEED_TASK_ID = "demo_seed_task"
DEMO_RESUME_NAME = "演示简历.pdf"
DEMO_POSITION_PREFIX = "demo_x_"

STATE_PENDING = "pending"
STATE_INITIALIZED = "initialized"
STATE_CLEARING = "clearing"

# 23 条演示记录参数（design 2.2：5 种状态 / 近 7 天均匀分布 / 3 平台分布）
DEMO_RECORD_PLAN: list[tuple[str, str, str, DeliveryStatus, int]] = [
    # (platform_id, position_id, title, status, days_ago)
    ("mock_platform", "demo_1", "Java 开发工程师", DeliveryStatus.delivered, 6),
    ("mock_platform", "demo_2", "Python 后端工程师", DeliveryStatus.delivered, 6),
    ("mock_platform", "demo_3", "前端开发工程师", DeliveryStatus.delivered, 5),
    ("mock_platform", "demo_4", "产品经理", DeliveryStatus.delivered, 5),
    ("mock_platform", "demo_5", "算法工程师", DeliveryStatus.delivered, 4),
    ("mock_platform", "demo_6", "数据分析师", DeliveryStatus.delivered, 4),
    ("mock_platform", "demo_7", "测试工程师", DeliveryStatus.viewed, 6),
    ("mock_platform", "demo_8", "运维工程师", DeliveryStatus.viewed, 5),
    ("mock_platform", "demo_9", "UI 设计师", DeliveryStatus.viewed, 4),
    ("mock_platform", "demo_10", "架构师", DeliveryStatus.viewed, 3),
    ("mock_platform", "demo_11", "客户端开发工程师", DeliveryStatus.viewed, 2),
    ("mock_platform", "demo_12", "安全工程师", DeliveryStatus.interview_invited, 5),
    ("mock_platform", "demo_13", "大数据工程师", DeliveryStatus.interview_invited, 4),
    ("mock_platform", "demo_14", "游戏策划", DeliveryStatus.interview_invited, 3),
    ("mock_platform", "demo_15", "量化研究员", DeliveryStatus.interview_invited, 2),
    ("boss_zhipin", "demo_x_boss_1", "Java 开发工程师（急聘）", DeliveryStatus.rejected, 5),
    ("boss_zhipin", "demo_x_boss_2", "后端开发专家", DeliveryStatus.rejected, 4),
    ("boss_zhipin", "demo_x_boss_3", "全栈工程师", DeliveryStatus.rejected, 3),
    ("boss_zhipin", "demo_x_boss_4", "微服务架构师", DeliveryStatus.failed, 4),
    ("zhilian", "demo_x_zl_1", "Python 高级工程师", DeliveryStatus.rejected, 5),
    ("zhilian", "demo_x_zl_2", "数据平台开发", DeliveryStatus.rejected, 3),
    ("zhilian", "demo_x_zl_3", "AI 应用工程师", DeliveryStatus.failed, 3),
    ("zhilian", "demo_x_zl_4", "云原生工程师", DeliveryStatus.failed, 2),
]

# 跨平台演示职位预置（demo_x_ 前缀，供记录页完整显示 title/company）
DEMO_CROSS_PLATFORM_POSITIONS = [
    ("boss_zhipin", "demo_x_boss_1", "Java 开发工程师（急聘）", "字节跳动", "北京", 25000, 45000, "互联网", "3-5年"),
    ("boss_zhipin", "demo_x_boss_2", "后端开发专家", "美团", "北京", 30000, 55000, "互联网", "5-10年"),
    ("boss_zhipin", "demo_x_boss_3", "全栈工程师", "哔哩哔哩", "上海", 20000, 38000, "互联网", "3-5年"),
    ("boss_zhipin", "demo_x_boss_4", "微服务架构师", "快手", "北京", 35000, 60000, "互联网", "5-10年"),
    ("zhilian", "demo_x_zl_1", "Python 高级工程师", "携程", "上海", 25000, 40000, "互联网", "3-5年"),
    ("zhilian", "demo_x_zl_2", "数据平台开发", "知乎", "北京", 28000, 45000, "互联网", "5-10年"),
    ("zhilian", "demo_x_zl_3", "AI 应用工程师", "小红书", "上海", 30000, 50000, "互联网", "3-5年"),
    ("zhilian", "demo_x_zl_4", "云原生工程师", "腾讯", "深圳", 32000, 55000, "互联网", "5-10年"),
]


def generate_demo_resume_pdf() -> bytes:
    """程序化生成虚构人物演示简历 PDF（PyMuPDF 内置 CJK 字体 china-s）。

    内容全虚构：演示姓名 + 3 段 IT 向虚构经历 + 138****0000 样式手机 +
    demo@example.com 邮箱；输出 %PDF- 魔数开头字节流。
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    width = page.rect.width
    y = 60

    def write(text: str, size: int = 11, bold: bool = False, gap: int = 6) -> None:
        nonlocal y
        font = "china-s"
        page.insert_font(fontname="cjk", fontfile=None, fontbuffer=None) if False else None
        page.insert_text((50, y), text, fontname=font, fontsize=size)
        y += size + gap

    write("李演示（求职演示专用档案）", 18)
    write("手机：138****0000（演示专用，非真实联系方式）", 10)
    write("邮箱：demo@example.com（演示专用，非真实联系方式）", 10)
    y += 6
    write("求职意向：后端开发工程师 / 全栈工程师（演示数据）", 12)
    write("期望城市：深圳（演示数据）  期望薪资：20K-35K（演示数据）", 11)
    y += 8

    write("技能（演示数据）", 13)
    write("· 熟练使用 Java / Python 进行后端服务开发，熟悉 Spring 与 FastAPI 框架", 11)
    write("· 熟悉 MySQL / Redis 常用数据结构与索引优化，了解消息队列与缓存体系", 11)
    write("· 了解 Docker 容器化部署与基础 CI/CD 流程，具备良好的编码习惯", 11)
    y += 8

    write("工作经历（演示数据，全虚构）", 13)
    write("2023.06 - 至今  某互联网公司（虚构）  后端开发工程师", 11)
    write("· 负责订单服务模块的开发与维护，参与接口设计与代码评审", 11)
    write("· 使用 Python 与 SQL 完成数据导出与报表工具，提升运营效率", 11)
    write("2021.07 - 2023.05  某软件公司（虚构）  初级开发工程师", 11)
    write("· 参与企业内部管理系统开发，负责基础 CRUD 与单元测试", 11)
    write("· 协助排查线上问题，编写技术文档与操作手册", 11)
    y += 8

    write("教育背景（演示数据）", 13)
    write("2017.09 - 2021.06  某大学（虚构）  计算机科学与技术 本科", 11)
    y += 10
    write("本简历为软件演示模式自动生成的虚构档案，用于展示软件功能；", 9)
    write("其中全部信息不对应任何真实人物与企业。", 9)

    data = doc.tobytes()
    doc.close()
    return data


class DemoModeService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------- 状态机 ----------

    def _state(self) -> str | None:
        return SettingRepository(self._session).get(DEMO_STATE_KEY)

    def _set_state(self, value: str) -> None:
        SettingRepository(self._session).set(DEMO_STATE_KEY, value)
        self._session.commit()

    def is_active(self) -> bool:
        return self._state() == STATE_INITIALIZED

    # ---------- 首启判定 ----------

    def _fresh_environment(self) -> bool:
        """四条件：无简历档案 / 无投递记录 / 无平台授权 / 无演示标记。"""
        has_resume = ResumeRepository(self._session).list_by_user(DEFAULT_USER_ID) != []
        _records, records_total = RecordRepository(self._session).list_by_user(DEFAULT_USER_ID, page=1, page_size=1)
        has_records = records_total > 0
        has_auth = AuthorizationRepository(self._session).get("mock_platform") is not None
        has_marker = self._state() is not None
        return not (has_resume or has_records or has_auth or has_marker)

    # ---------- 幂等注入编排 ----------

    def bootstrap(self) -> None:
        """lifespan 装配点调用：off 即时返回；clearing 续清；fresh 注入；否则旁观。"""
        if settings.demo_mode != "auto":
            return
        state = self._state()
        if state == STATE_INITIALIZED:
            return
        if state == STATE_CLEARING:
            self.reset()
            return
        if state == STATE_PENDING:
            self._inject_all()
            return
        if not self._fresh_environment():
            logger.info("demo_mode_skip_existing_data", user_id=DEFAULT_USER_ID)
            return
        self._set_state(STATE_PENDING)
        self._inject_all()

    def _inject_all(self) -> None:
        """注入序列（每步先查后插保证幂等；中断后重启经 pending 续跑补齐）。"""
        try:
            self._inject_demo_resume()
            self._inject_demo_authorization()
            self._inject_cross_platform_positions()
            self._inject_demo_task_and_records()
            self._set_state(STATE_INITIALIZED)
            logger.info("demo_mode_initialized", user_id=DEFAULT_USER_ID)
        except Exception:  # noqa: BLE001
            self._session.rollback()
            logger.exception("demo_mode_inject_failed")

    def _inject_demo_resume(self) -> None:
        repo = ResumeRepository(self._session)
        if repo.list_by_user(DEFAULT_USER_ID):
            return
        from app.config import settings as app_settings
        from app.infra.crypto import get_crypto
        from app.services.resume_service import ResumeService

        service = ResumeService(self._session, get_crypto(), app_settings.resume_storage_dir)
        service.upload(DEFAULT_USER_ID, DEMO_RESUME_NAME, generate_demo_resume_pdf())

    def _inject_demo_authorization(self) -> None:
        """复用既有授权服务：一条调用完成演示授权 + 585 职位拉取。"""
        repo = AuthorizationRepository(self._session)
        if repo.get("mock_platform") is not None:
            return
        from app.infra.crypto import get_crypto
        from app.platforms.registry import get_registry
        from app.services.authorization_service import AuthorizationService

        AuthorizationService(self._session, get_crypto(), get_registry()).authorize(
            DEFAULT_USER_ID, "mock_platform", "valid-token"
        )

    def _inject_cross_platform_positions(self) -> None:
        pos_repo = PositionRepository(self._session)
        existing = pos_repo.get_by_ids([p[1] for p in DEMO_CROSS_PLATFORM_POSITIONS])
        existing_ids = {p.position_id for p in existing}
        expire = datetime.now() + timedelta(days=30)
        for platform_id, position_id, title, company, city, smin, smax, industry, exp in DEMO_CROSS_PLATFORM_POSITIONS:
            if position_id in existing_ids:
                continue
            pos_repo.upsert(
                JobPosition(
                    position_id=position_id,
                    platform_id=platform_id,
                    title=title,
                    company=company,
                    city=city,
                    salary_min=smin,
                    salary_max=smax,
                    industry=industry,
                    experience_req=exp,
                    publish_expire_at=expire,
                    fetched_at=datetime.now(),
                )
            )

    def _inject_demo_task_and_records(self) -> None:
        task_repo = TaskRepository(self._session)
        record_repo = RecordRepository(self._session)
        if task_repo.get(DEMO_SEED_TASK_ID) is None:
            resume = ResumeRepository(self._session).get_default(DEFAULT_USER_ID)
            content_hash = hashlib.sha256(generate_demo_resume_pdf()).hexdigest()
            snapshot = ResumeSnapshot(
                name=DEMO_RESUME_NAME,
                format="pdf",
                content_hash=content_hash,
                created_at=resume.created_at if resume else datetime.now(),
            )
            task_repo.add(
                DeliveryTask(
                    task_id=DEMO_SEED_TASK_ID,
                    user_id=DEFAULT_USER_ID,
                    status=TaskStatus.completed,
                    created_at=datetime.now() - timedelta(days=7),
                    resume_id=resume.resume_id if resume else "",
                    resume_snapshot=snapshot,
                    target_position_ids=[p[1] for p in DEMO_RECORD_PLAN],
                    success_count=19,
                    failed_count=4,
                    skipped_count=0,
                )
            )
        existing_records = record_repo.list_by_task(DEMO_SEED_TASK_ID)
        if existing_records:
            return
        resume = ResumeRepository(self._session).get_default(DEFAULT_USER_ID)
        snapshot = ResumeSnapshot(
            name=DEMO_RESUME_NAME,
            format="pdf",
            content_hash=hashlib.sha256(generate_demo_resume_pdf()).hexdigest(),
            created_at=resume.created_at if resume else datetime.now(),
        )
        for platform_id, position_id, _title, status, days_ago in DEMO_RECORD_PLAN:
            created = datetime.now() - timedelta(days=days_ago, hours=3)
            delivered_at = None
            failure_reason = None
            if status != DeliveryStatus.pending:
                delivered_at = created + timedelta(minutes=2)
            if status == DeliveryStatus.failed:
                failure_reason = "演示数据：模拟投递失败样例"
            record_repo.add(
                DeliveryRecord(
                    record_id=new_id("rec_"),
                    user_id=DEFAULT_USER_ID,
                    task_id=DEMO_SEED_TASK_ID,
                    position_id=position_id,
                    platform_id=platform_id,
                    status=status,
                    created_at=created,
                    delivered_at=delivered_at,
                    status_updated_at=created + timedelta(hours=1),
                    failure_reason=failure_reason,
                    resume_snapshot=snapshot,
                )
            )
        self._session.commit()

    # ---------- 一键清除（四键圈定，决策 D3） ----------

    def clearable_summary(self) -> dict:
        """可清除范围统计（前端确认弹窗展示）。"""
        resume_repo = ResumeRepository(self._session)
        demo_resumes = [r for r in resume_repo.list_by_user(DEFAULT_USER_ID) if r.name == DEMO_RESUME_NAME]
        record_repo = RecordRepository(self._session)
        records, _ = record_repo.list_by_user(DEFAULT_USER_ID, page=1, page_size=100000)
        demo_records = [r for r in records if r.task_id == DEMO_SEED_TASK_ID]
        positions, _total = PositionRepository(self._session).list_active(page=1, page_size=100000)
        demo_positions = [p for p in positions if p.position_id.startswith(DEMO_POSITION_PREFIX)]
        return {
            "resumes": len(demo_resumes),
            "records": len(demo_records),
            "positions": len(demo_positions),
        }

    def reset(self) -> dict:
        """退出演示模式：四键圈定清除；中断以 clearing 承接（下次启动续清）。

        平台授权不在清除范围（用户既有授权保留）；非演示态幂等空操作返回全 0。
        """
        state = self._state()
        if state is None:
            return {"resumes": 0, "records": 0, "positions": 0, "markers": 0}
        try:
            self._set_state(STATE_CLEARING)
            cleared = {"resumes": 0, "records": 0, "positions": 0, "markers": 0}

            task_repo = TaskRepository(self._session)
            record_repo = RecordRepository(self._session)
            if task_repo.get(DEMO_SEED_TASK_ID) is not None:
                for record in record_repo.list_by_task(DEMO_SEED_TASK_ID):
                    record_repo.delete_record(record.record_id)
                    cleared["records"] += 1
                task_repo.delete_task(DEMO_SEED_TASK_ID)

            resume_repo = ResumeRepository(self._session)
            from app.config import settings as app_settings
            from app.infra.crypto import get_crypto
            from app.services.resume_service import ResumeService

            resume_service = ResumeService(
                self._session, get_crypto(), app_settings.resume_storage_dir
            )
            for resume in resume_repo.list_by_user(DEFAULT_USER_ID):
                if resume.name == DEMO_RESUME_NAME:
                    resume_service.delete(DEFAULT_USER_ID, resume.resume_id)
                    cleared["resumes"] += 1

            pos_repo = PositionRepository(self._session)
            positions, _total = pos_repo.list_active(page=1, page_size=100000)
            for position in positions:
                if position.position_id.startswith(DEMO_POSITION_PREFIX):
                    pos_repo.delete_position(position.position_id)
                    cleared["positions"] += 1

            SettingRepository(self._session).delete(DEMO_STATE_KEY)
            self._session.commit()
            cleared["markers"] = 1
            logger.info("demo_mode_cleared", **cleared)
            return cleared
        except Exception:  # noqa: BLE001
            self._session.rollback()
            logger.exception("demo_mode_clear_failed")
            self._set_state(STATE_CLEARING)
            raise

    def status(self) -> dict:
        """GET /api/v1/demo-mode 响应体。"""
        state = self._state()
        return {
            "active": state == STATE_INITIALIZED,
            "state": state or "",
            "clearable_summary": self.clearable_summary() if state == STATE_INITIALIZED else
            {"resumes": 0, "records": 0, "positions": 0},
        }