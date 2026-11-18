"""统一错误码体系（design 2.2.1）。

| 错误码 | HTTP 状态 | 含义 |
|--------|----------|------|
| 40001 | 400 | 文件格式不支持 |
| 40002 | 400 | 文件大小超过限制 |
| 40003 | 422 | 参数非法/文件无法解析 |
| 40004 | 409 | 简历档案重名 |
| 40901 | 409 | 30 天内重复投递拦截 |
| 40902 | 409 | 已达每日投递上限 |
| 40903 | 409 | 投递任务状态冲突 |
| 41001 | 403 | 平台授权已过期 |
| 41002 | 429 | 平台限流/风控拦截 |
| 41003 | 503 | 平台暂不可用（降级中） |
| 40401 | 404 | 资源不存在 |
"""


class AppError(Exception):
    def __init__(self, code: int, message: str, http_status: int) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(f"[{code}] {message}")


class UnsupportedFormatError(AppError):
    def __init__(self, message: str = "仅支持 PDF 或 Word 格式") -> None:
        super().__init__(40001, message, 400)


class FileTooLargeError(AppError):
    def __init__(self, message: str = "文件大小超过限制（20MB）") -> None:
        super().__init__(40002, message, 400)


class InvalidParamError(AppError):
    def __init__(self, message: str = "参数非法") -> None:
        super().__init__(40003, message, 422)


class DuplicateResumeNameAPIError(AppError):
    def __init__(self, message: str = "简历档案名称已存在") -> None:
        super().__init__(40004, message, 409)


class DuplicateDeliveryError(AppError):
    def __init__(self, message: str = "该职位 30 天内已投递过") -> None:
        super().__init__(40901, message, 409)


class DailyLimitReachedError(AppError):
    def __init__(self, message: str = "已达今日投递上限") -> None:
        super().__init__(40902, message, 409)


class TaskStateConflictError(AppError):
    def __init__(self, message: str = "投递任务状态冲突") -> None:
        super().__init__(40903, message, 409)


class PlatformAuthExpiredError(AppError):
    def __init__(self, message: str = "平台授权已过期") -> None:
        super().__init__(41001, message, 403)


class PlatformRateLimitedError(AppError):
    def __init__(self, message: str = "平台限流/风控拦截") -> None:
        super().__init__(41002, message, 429)


class PlatformDegradedError(AppError):
    def __init__(self, message: str = "平台暂不可用（降级中）") -> None:
        super().__init__(41003, message, 503)


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(40401, message, 404)

class RiskUnconfirmedError(AppError):
    def __init__(self, message: str = "请先阅读并确认平台接入风险告知") -> None:
        super().__init__(42001, message, 403)


class PlatformAlreadyAuthorizedError(AppError):
    def __init__(self, message: str = "该平台已绑定授权凭证，请先撤销后再授权") -> None:
        super().__init__(42002, message, 409)


class RatePolicyExceededError(AppError):
    def __init__(self, message: str = "限流设置超过安全上限（投递 ≤30/小时）") -> None:
        super().__init__(42003, message, 422)


class AuthSessionConflictError(AppError):
    def __init__(self, message: str = "授权会话冲突或已终态") -> None:
        super().__init__(42004, message, 409)

class AiModelConfigNotFoundError(AppError):
    def __init__(self, message: str = "AI 模型配置不存在") -> None:
        super().__init__(43001, message, 404)


class AiConfigNameConflictError(AppError):
    def __init__(self, message: str = "已存在同名模型配置") -> None:
        super().__init__(43002, message, 409)


class AiApiKeyRequiredError(AppError):
    def __init__(self, message: str = "云端服务商必须配置您自己的 API Key") -> None:
        super().__init__(43003, message, 422)


class AiConfigNotTestedError(AppError):
    def __init__(self, message: str = "激活前需先通过连通性测试（或明确确认强制激活）") -> None:
        super().__init__(43004, message, 409)


class GreetingEditConflictError(AppError):
    def __init__(self, message: str = "任务已确认或已终态，招呼语不可再编辑") -> None:
        super().__init__(43005, message, 409)


class GreetingTooLongError(AppError):
    def __init__(self, message: str = "招呼语超过长度上限") -> None:
        super().__init__(43006, message, 422)