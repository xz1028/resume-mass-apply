"""真实招聘平台接入组件：浏览器自动化引擎 + 三平台适配器 + 接入治理。

零侵入叠加于既有 SPI 契约（app/platforms/spi.py）之上；
组件仅引用既有 infra（crypto/logging/metrics/audit/rate_limiter）与 repositories。
"""