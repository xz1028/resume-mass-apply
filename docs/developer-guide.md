# 开发者指南（Developer Guide）

面向开发者与二次贡献者的技术文档：源码运行、API 契约、适配器扩展、测试与目录结构。

## 源码运行方式

```bash
# 1. 克隆仓库后安装依赖（建议使用虚拟环境；Windows）
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# 2. 启动（零配置，全部配置项有默认值）
uvicorn app.main:app --host 0.0.0.0 --port 8000
# 或双击 start.bat（含环境自检/就绪探测/自动打开浏览器）

# 3. 验证
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/platforms
```

配置项说明见 `.env.example`（环境变量前缀 `RMA_`，含 `RMA_DEMO_MODE` 演示模式门控，源码形态默认 off）。

## 平台接入说明

- **模拟招聘平台**（内置）：开箱即用，演示凭证 `valid-token`，授权后自动拉取 585 个演示职位
- **真实平台**（BOSS直聘 / 智联招聘 / 前程无忧）：默认禁用，通过浏览器自动化接入（需 `pip install playwright`）
  - 启用前需在「平台授权与设置」页确认风险告知（非官方通道，账号存在被限制/封禁风险）
  - 推荐授权方式：浏览器登录授权（打开受控浏览器窗口，您在窗口中登录平台，登录态加密保存，密码不落盘）
  - 验证码一律转人工：弹出待处理横幅，点击「前往处理」在浏览器窗口中完成
  - 投递限流保守默认 20/小时，安全上限 30/小时不可超越
  - 禁用平台立即停止一切交互，历史投递记录保留可查

## AI 智能匹配与招呼语

- **AI 匹配评分**：大模型阅读职位 JD 与简历，输出 0-100 匹配度与评分理由；与规则评分并行对比展示（渐进刷新不阻塞首屏），AI 评分优先用于推荐排序与条件圈选
- **AI 招呼语**：按 JD 定制化打招呼消息（语气可选、真实性约束、不含联系方式），投递清单确认环节可预览与编辑
- **七种接入方式**：DeepSeek / 通义千问 / Kimi / 智谱 / 华为云磐古大模型 / OpenAI 兼容接口 / 本地 Ollama（统一 OpenAI 兼容协议）
- **华为云 ModelArts 端点配置示例**：AI 模型配置页 → 新增配置 → 服务商选"华为云磐古大模型"→
  接口地址填您的 ModelArts 服务端点（形如 `https://<endpoint>.apigw.xxxx/v1`，OpenAI 兼容）→
  模型名填您的部署名称 → 粘贴您自己的 API Key → 测试连通 → 激活
- **安全与隐私**：API Key AES-256-GCM 加密存储、界面永不回显、软件不内置任何 Key；简历默认脱敏手机号/邮箱后发送；本地 Ollama 模式数据不出本机
- **降级保障**：未配置/调用失败/余额不足时自动回退规则评分与固定模板招呼语，全部既有功能不受影响
- **成本控制**：JD/简历截断、同岗位缓存去重（24h TTL）、重试 ≤1 次、失败冷却 10 分钟

## API 使用示例（curl）

```bash
# 1. 上传简历（首个档案自动设为默认）
curl -F "file=@resume.pdf" http://localhost:8000/api/v1/resumes

# 2. 配置联系方式与求职意向（联系方式必须为有效手机号或邮箱）
curl -X PUT -d '{"user_id":"local_user","contact":{"phone":"13800138000"},"intention":{"city":"深圳","salary_min":15000}}' http://localhost:8000/api/v1/profile

# 3. 授权招聘平台（凭证加密存储，日志全程脱敏）
curl -d '{"credential":"valid-token"}' http://localhost:8000/api/v1/platforms/mock_platform/authorization

# 4. 筛选职位（自动应用去重、黑名单与过期过滤）
curl "http://localhost:8000/api/v1/positions?city=深圳&salary_min=15000"

# 5. 获取推荐列表（按匹配度降序）
curl "http://localhost:8000/api/v1/recommendations?top_n=50"

# 6. 设置匹配阈值（低于阈值不进入自动投递圈选范围）
curl -X PUT -d '{"auto_apply_threshold":60}' http://localhost:8000/api/v1/matching-settings

# 7. 创建投递任务（方式一：手动勾选 / 方式二：条件圈选）
curl -d '{"position_ids":["p1","p2"]}' http://localhost:8000/api/v1/delivery-tasks
curl -d '{"filter_condition":{"city":"深圳","min_match_score":80}}' http://localhost:8000/api/v1/delivery-tasks

# 8. 确认投递（清单确认后执行；未确认不产生任何投递记录）
curl -X POST http://localhost:8000/api/v1/delivery-tasks/<task_id>/confirm

# 9. 查询任务执行摘要 / 10. 投递记录与统计
curl http://localhost:8000/api/v1/delivery-tasks/<task_id>
curl "http://localhost:8000/api/v1/delivery-records?status=interview_invited"
curl http://localhost:8000/api/v1/delivery-statistics

# 11. 黑名单（公司精确匹配 / 职位关键词包含匹配，立即生效）
curl -d '{"type":"company","content":"某公司"}' http://localhost:8000/api/v1/blacklist

# 12. 每日投递上限 / 13. 撤销平台授权
curl -X PUT -d '{"daily_limit":50}' http://localhost:8000/api/v1/delivery-settings
curl -X DELETE http://localhost:8000/api/v1/platforms/mock_platform/authorization

# 演示模式（绿色包形态）
curl http://localhost:8000/api/v1/demo-mode
curl -X POST http://localhost:8000/api/v1/demo-mode/reset

# 浏览器组件状态（核心绿色包为可选增强）
curl http://localhost:8000/api/v1/platform-access/browser-component

# 监控指标（Prometheus 格式）
curl http://localhost:8000/metrics
```

错误码体系：40001 格式不支持 / 40002 超大小 / 40003 参数非法 / 40004 档案重名 /
40901 重复投递 / 40902 每日上限 / 40903 任务状态冲突 / 41001 授权过期 /
41002 平台限流 / 41003 平台降级 / 42001-42004 平台接入治理 /
43001-43006 AI 模型配置 / 40401 资源不存在。

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

演示数据白名单：`app/platforms/demo_data/` 三 JSON（公司/行业岗位/城市薪资档位），
新增公司或岗位仅需改数据文件，重新生成自动包含（详见 `loader.py` 校验规则）。

## 运行测试

```bash
pip install -e ".[dev]"
pytest tests/unit -q          # 单元测试
pytest tests/integration -q  # 集成测试（全链路 + 异常场景）
pytest -q                    # 全部测试
```

CI：`.github/workflows/ci.yml`（Windows runner + Python 3.11，push/PR 触发全量测试）。

## 构建发布包

```bash
pip install pyinstaller
python scripts/build_release.py      # 产出 release/ 三件套（zip + SHA256 + RELEASE_NOTES）
```

发布前检查（测试全绿/材料齐备/脱敏/LICENSE 就位）内建于构建脚本，任一不满足阻断发布。

## 目录结构

```
app/
  config.py            统一配置（环境变量覆盖）
  main.py             FastAPI 应用工厂
  domain/             领域模型与状态机（不依赖存储框架）
  repositories/       ORM 表定义与各实体 Repository
  platforms/          平台适配器 SPI、注册表、模拟平台、演示数据白名单
  parsers/            简历文本提取（PDF/Word）
  matching/           匹配引擎（多因子加权评分）
  services/           业务服务（简历/职位/匹配/投递/跟踪/授权/演示模式）
  ai/                 AI 智能匹配与招呼语组件（LLM 客户端/配置管理/编排）
  real_platform/      真实平台浏览器自动化接入
  infra/              数据库、加密、日志、审计、限流、通知、调度、指标
  api/v1/             REST 路由（统一错误码体系）
  static/             Vue 3 前端（本地托管运行时）
scripts/              构建流水线（PyInstaller spec/启动器模板/一键构建）
tests/
  unit/               单元测试
  integration/        集成测试
```