"""AI 智能匹配与招呼语组件（增强层，非替换层）。

三层结构：llm/ 客户端层 → matching/、greeting/、config/ 业务服务层 → api.py、tasks.py 接入编排层。
兼容性红线：AI 未启用/降级期间全部既有接口对外行为不变；未配置 Key 时零模型调用；
AI 不进推荐主链路（GET /recommendations 的 match_score 语义与 5 秒响应零改动）。
包内仅引用既有 app/infra/、app/repositories/、app/config.py 与 real_platform 命令机制，
禁止既有 services 反向 import 本组件。
"""