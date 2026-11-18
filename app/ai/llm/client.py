"""OpenAI 兼容统一客户端：POST {base_url}/chat/completions 单端点。

红线约束：
- Key 仅注入 Authorization 头发往激活配置的 base_url（测试草稿 Key 不落库）
- 不配置代理（强制直连）
- 超时分级：匹配 30s / 招呼语 20s / 测试 15s
- 重试 ≤1 且仅限可重试类（timeout/rate_limited/unreachable）
- 结构化日志白名单字段：禁 Key 明文、禁简历明文、禁招呼语明文
"""

import asyncio
import time

import httpx

from app.ai.llm.classifier import classify_exception, classify_status, failure_message, is_retryable
from app.ai.models import CallKind, FailureKind
from app.infra.logging import get_logger

logger = get_logger("llm_client")

TIMEOUT_SECONDS = {
    CallKind.match: 30,
    CallKind.greeting: 20,
    CallKind.test: 15,
}

RETRYABLE_KINDS = {FailureKind.timeout, FailureKind.rate_limited, FailureKind.unreachable}


class LlmCallError(Exception):
    """调用失败（含分类与用户可读消息）；由调用方决定降级路径。"""

    def __init__(self, kind: FailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class OpenAICompatClient:
    """无状态客户端：每次调用独立请求（连接复用由 httpx 客户端管理）。"""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            proxies=None,  # 强制直连，不配置代理
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def chat(
        self,
        base_url: str,
        model_name: str,
        api_key: str | None,
        messages: list[dict],
        call_kind: CallKind,
        provider: str,
        max_tokens: int | None = None,
    ) -> str:
        """单次调用（含 ≤1 次重试）。返回模型文本响应；失败抛 LlmCallError。"""
        url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"model": model_name, "messages": messages}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        timeout = httpx.Timeout(float(TIMEOUT_SECONDS.get(call_kind, 30)))

        started = time.monotonic()
        attempted = 0
        last_error: LlmCallError | None = None
        while attempted < 2:
            attempted += 1
            try:
                resp = await self._http.post(url, json=payload, headers=headers, timeout=timeout)
            except httpx.TimeoutException as exc:
                last_error = LlmCallError(FailureKind.timeout, failure_message(FailureKind.timeout, provider))
                logger.warning("llm_call_failed", provider=provider, call_type=call_kind.value,
                               kind=FailureKind.timeout.value, reason=str(exc)[:120], attempt=attempted)
            except httpx.HTTPError as exc:
                kind = classify_exception(exc)
                last_error = LlmCallError(kind, failure_message(kind, provider))
                logger.warning("llm_call_failed", provider=provider, call_type=call_kind.value,
                               kind=kind.value, reason=str(exc)[:120], attempt=attempted)
            else:
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                        if not isinstance(content, str) or not content.strip():
                            raise ValueError("空响应")
                        return content
                    except (ValueError, KeyError, TypeError) as exc:
                        kind = FailureKind.bad_format
                        last_error = LlmCallError(kind, failure_message(kind, provider))
                        logger.warning("llm_call_failed", provider=provider, call_type=call_kind.value,
                                       kind=kind.value, reason=f"响应解析失败: {exc}", attempt=attempted)
                else:
                    body_text = ""
                    try:
                        body_text = resp.text[:500]
                    except Exception:  # noqa: BLE001
                        pass
                    kind = classify_status(resp.status_code, body_text)
                    last_error = LlmCallError(kind, failure_message(kind, provider))
                    logger.warning("llm_call_failed", provider=provider, call_type=call_kind.value,
                                   kind=kind.value, status=resp.status_code, attempt=attempted)

            if last_error is not None and not is_retryable(last_error.kind):
                break
            if attempted < 2 and last_error is not None:
                await asyncio.sleep(0.8)

        duration_ms = int((time.monotonic() - started) * 1000)
        if last_error is None:
            last_error = LlmCallError(FailureKind.unreachable, "未知调用失败")
        self._log_call(provider, call_kind, attempted, duration_ms)
        raise last_error

    async def test_connectivity(
        self, base_url: str, model_name: str, api_key: str | None, provider: str
    ) -> dict:
        """连通性测试：轻量请求（极小 max_tokens），15 秒硬超时。"""
        started = time.monotonic()
        try:
            content = await self.chat(
                base_url=base_url,
                model_name=model_name,
                api_key=api_key,
                messages=[
                    {"role": "user", "content": "回复：ok"},
                ],
                call_kind=CallKind.test,
                provider=provider,
                max_tokens=8,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            self._log_call(provider, CallKind.test, 1, duration_ms)
            return {"status": "success", "message": "连通正常", "duration_ms": duration_ms, "reply": content[:40]}
        except LlmCallError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            self._log_call(provider, CallKind.test, 1, duration_ms)
            return {
                "status": exc.kind.value if exc.kind in (
                    FailureKind.invalid_key, FailureKind.insufficient_quota, FailureKind.unreachable
                ) else "unreachable",
                "message": exc.message,
                "duration_ms": duration_ms,
                "reply": "",
            }

    @staticmethod
    def _log_call(provider: str, call_kind: CallKind, attempted: int, duration_ms: int) -> None:
        """结构化日志白名单：不含 Key/简历/招呼语明文。"""
        logger.info(
            "llm_call_completed",
            provider=provider,
            call_type=call_kind.value,
            attempted=attempted,
            duration_ms=duration_ms,
        )


_client: OpenAICompatClient | None = None


def get_llm_client() -> OpenAICompatClient:
    global _client
    if _client is None:
        _client = OpenAICompatClient()
    return _client


def reset_llm_client_singleton() -> None:
    global _client
    _client = None