# 就业海投简历系统

聚合多招聘平台职位信息，按求职意向智能匹配并批量投递简历的单机软件。

技术栈：Python 3.11 + FastAPI + SQLite(WAL) + APScheduler + AES-256-GCM。

## 功能概览

- **简历档案管理**：PDF/Word 上传（≤20MB）、多版本管理、默认简历、删除保护（快照）、加密存储
- **职位获取与筛选**：定时拉取（≤24h）、多条件筛选、去重、黑名单过滤、过期清理
- **智能匹配**：技能/经验/城市/薪资多因子加权评分（0-100）、匹配阈值、推荐排序、缓存
- **批量投递**：手动勾选/条件圈选、投递清单确认、30 天重复拦截、每日上限、令牌桶限流、失败重试
- **状态跟踪**：状态机受控流转、定期同步（≤12h）、面试邀请/不合适通知、投递统计
- **平台适配器**：SPI 插件机制，新增招聘平台零侵入

## 安装与启动

```bash
# 1. 安装依赖（建议使用虚拟环境）
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .

# 2. 启动（零配置，全部配置项有默认值）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. 验证
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/platforms
```

配置项说明见 `.env.example`（环境变量前缀 `RMA_`）。

## API 使用示例（curl）

```bash
# 1. 上传简历（首个档案自动设为默认）
curl -F "file=@resume.pdf" http://localhost:8000/api/v1/resumes

# 2. 配置联系方式与求职意向（联系方式必须为有效手机号或邮箱）
curl -X PUT -d '{"user_id":"local_user","contact":{"phone":"13800138000"},"intention":{"city":"深圳","salary_min":15000}}' http://localhost:8000/api/v1/profile

# 3. 授权招聘平台（凭证加密存储，日志全程脱敏）
curl -d '{"credential":"your-token"}' http://localhost:8000/api/v1/platforms/mock_platform/authorization

# 4. 筛选职位（自动应用去重、黑名单与过期过滤）
curl "http://localhost:8000/api/v1/positions?city=深圳&salary_min=15000"

# 5. 获取推荐列表（按匹配度降序）
curl "http://localhost:8000/api/v1/recommendations?top_n=50"

# 6. 设置匹配阈值（低于阈值不进入自动投递圈选范围）
curl -X PUT -d '{"auto_apply_threshold":60}' http://localhost:8000/api/v1/matching-settings

# 7. 创建投递任务（方式一：手动勾选）
curl -d '{"position_ids":["p1","p2"]}' http://localhost:8000/api/v1/delivery-tasks
# 7. 创建投递任务（方式二：条件圈选，配合匹配阈值）
curl -d '{"filter_condition":{"city":"深圳","min_match_score":80}}' http://localhost:8000/api/v1/delivery-tasks

# 8. 确认投递（展示清单确认后执行；未确认不产生任何投递记录）
curl -X POST http://localhost:8000/api/v1/delivery-tasks/<task_id>/confirm

# 9. 查询任务执行摘要（成功数/失败数/跳过数）
curl http://localhost:8000/api/v1/delivery-tasks/<task_id>

# 10. 投递记录与统计
curl "http://localhost:8000/api/v1/delivery-records?status=interview_invited"
curl http://localhost:8000/api/v1/delivery-statistics

# 11. 黑名单（公司全名精确匹配 / 职位关键词包含匹配，立即生效）
curl -d '{"type":"company","content":"某公司"}' http://localhost:8000/api/v1/blacklist

# 12. 每日投递上限
curl -X PUT -d '{"daily_limit":50}' http://localhost:8000/api/v1/delivery-settings

# 13. 撤销平台授权（立即停止该平台一切投递）
curl -X DELETE http://localhost:8000/api/v1/platforms/mock_platform/authorization

# 监控指标（Prometheus 格式）
curl http://localhost:8000/metrics
```

错误码体系：40001 格式不支持 / 40002 超大小 / 40003 参数非法 / 40004 档案重名 /
40901 重复投递 / 40902 每日上限 / 40903 任务状态冲突 / 41001 授权过期 /
41002 平台限流 / 41003 平台降级 / 40401 资源不存在。

## 新平台适配器接入指南

新增招聘平台 = 实现四个 SPI 方法 + 注册，**无需修改任何上层代码**：

```python
# app/platforms/zhilian_adapter.py
from app.platforms.spi import (
    PlatformAdapter, PositionDTO, ApplyResult, StatusReceipt,
    PlatformRecordRef, EncryptedResumeRef, RateLimitPolicy,
)

class ZhilianAdapter:
    platform_id = "zhilian"
    rate_limit = RateLimitPolicy(max_per_hour=30.0)

    def fetch_positions(self, intent, since): ...        # 拉取职位 -> list[PositionDTO]
    def submit_application(self, position, resume_file, contact) -> ApplyResult: ...
    def fetch_application_status(self, refs) -> list[StatusReceipt]: ...
    def validate_authorization(self, credential) -> AuthStatus: ...
```

在 `app/main.py` 的 `_register_default_platforms()` 中注册：

```python
registry.register(ZhilianAdapter(), name="智联招聘")
```

适配器异常必须归类为三类之一：`PlatformAuthExpiredError` / `PlatformRateLimitedError` /
`PlatformUnavailableError`，投递引擎按异常类型自动路由跳过/暂停/重试策略。

## 运行测试

```bash
pip install -e ".[dev]"
pytest tests/unit -q          # 单元测试
pytest tests/integration -q  # 集成测试（全链路 + 异常场景）
pytest -q                    # 全部测试
```

## 目录结构

```
app/
  config.py            统一配置（环境变量覆盖）
  main.py             FastAPI 应用工厂
  domain/             领域模型与状态机（不依赖存储框架）
  repositories/       ORM 表定义与各实体 Repository
  platforms/          平台适配器 SPI、注册表、模拟平台
  parsers/            简历文本提取（PDF/Word）
  matching/           匹配引擎（多因子加权评分）
  services/           业务服务（简历/职位/匹配/投递/跟踪/授权）
  infra/              数据库、加密、日志、审计、限流、通知、调度、指标
  api/v1/             REST 路由（23 个接口 + 统一错误码）
tests/
  unit/               单元测试
  integration/        集成测试
```