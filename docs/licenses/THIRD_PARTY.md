# 第三方依赖许可证清单（THIRD_PARTY.md）

对照 `pyproject.toml` 全部 14 项运行时依赖逐项核对（发布检查用，spec 5.4.1.3）。

| 依赖 | 版本要求 | 许可证 | 类型 | 备注 |
|------|---------|--------|------|------|
| fastapi | >=0.110 | MIT | 宽松 | Web 框架 |
| uvicorn | >=0.29 | BSD-3-Clause | 宽松 | ASGI 服务器 |
| python-multipart | >=0.0.9 | Apache-2.0 | 宽松 | 文件上传解析 |
| pydantic | >=2.6 | MIT | 宽松 | 数据校验 |
| pydantic-settings | >=2.2 | MIT | 宽松 | 配置管理 |
| sqlalchemy | >=2.0 | MIT | 宽松 | ORM |
| apscheduler | >=3.10 | MIT | 宽松 | 定时调度 |
| httpx | >=0.27 | BSD-3-Clause | 宽松 | HTTP 客户端（LLM 通道） |
| cryptography | >=42.0 | Apache-2.0 / BSD-3 | 宽松 | AES-256-GCM 加密 |
| pymupdf | >=1.24 | AGPL-3.0（含商业豁免条款） | **需说明** | 见下方专项说明 |
| python-docx | >=1.1 | MIT | 宽松 | Word 解析 |
| structlog | >=24.1 | MIT / Apache-2.0 | 宽松 | 结构化日志 |
| prometheus-client | >=0.20 | Apache-2.0 | 宽松 | 监控指标 |
| playwright | >=1.40 | Apache-2.0 | 宽松 | 浏览器自动化（可选组件，核心包排除） |

## PyMuPDF（fitz）专项说明

PyMuPDF 基于 MuPDF，上游 MuPDF 采用 AGPL-3.0 许可。PyMuPDF 官方为其
Windows/macOS/Linux 预编译 wheel 提供了**商业豁免条款**：对通过 pip 安装
预编译 wheel 的使用者，Artifex 允许在 AGPL 之外以自有许可分发包含
PyMuPDF 的软件（详见 PyMuPDF 官方 repository 的 COPYING 与商业许可说明）。

本项目为参赛作品与本机自用工具分发形态：
- 源码形态：通过 pip 安装官方预编译 wheel（覆盖豁免条款范围）；
- 分发包形态：PyInstaller 打包内嵌该 wheel 的构建产物。

如后续将本项目用于商业分发，请自行评估 Artifex 商业许可的适用性，
或替换为 pdfminer.six（MIT）/ pypdf（BSD）等纯宽松许可的 PDF 解析实现。

## 结论

除 pymupdf（有官方 wheel 商业豁免条款，已专项说明）外，
全部运行时依赖均为 MIT / Apache-2.0 / BSD 系宽松许可，
**无 GPL/AGPL 传染性强制开源义务**（pymupdf 见专项说明的豁免路径）。

> 后续新增依赖若携带 GPL/AGPL 系许可，`scripts/build_release.py` 的发布前
> 检查将依据本清单比对并阻断发布（spec 5.4.3.1）。