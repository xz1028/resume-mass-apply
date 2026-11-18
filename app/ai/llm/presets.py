"""服务商预设注册表：六种接入方式，仅为端点常量 + 是否需 Key 标识 + 展示名。

红线：预设不含任何 Key（spec 5.1.1.8 禁止项）；base_url 全部可被用户配置覆盖。
"""

from app.ai.models import ProviderKind

PROVIDER_PRESETS = {
    ProviderKind.deepseek.value: {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "requires_key": True,
        "default_model": "deepseek-chat",
        "note": "性价比高，国内直连",
    },
    ProviderKind.qwen.value: {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "requires_key": True,
        "default_model": "qwen-plus",
        "note": "阿里云百炼兼容模式",
    },
    ProviderKind.kimi.value: {
        "label": "Kimi（月之暗面）",
        "base_url": "https://api.moonshot.cn/v1",
        "requires_key": True,
        "default_model": "moonshot-v1-8k",
        "note": "长上下文",
    },
    ProviderKind.zhipu.value: {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "requires_key": True,
        "default_model": "glm-4-flash",
        "note": "GLM 系列",
    },
    ProviderKind.pangu.value: {
        "label": "华为云磐古大模型",
        "base_url": "https://api.modelarts-ma.aliyun.com/v1",
        "requires_key": True,
        "default_model": "pangu-nlp",
        "note": "华为云 ModelArts 大模型服务，用户自带 Key",
    },
    ProviderKind.openai_compat.value: {
        "label": "OpenAI 兼容接口",
        "base_url": "https://api.openai.com/v1",
        "requires_key": True,
        "default_model": "gpt-4o-mini",
        "note": "自定义兼容服务必填接口地址",
    },
    ProviderKind.ollama.value: {
        "label": "本地 Ollama",
        "base_url": "http://localhost:11434/v1",
        "requires_key": False,
        "default_model": "qwen2.5:7b",
        "note": "数据不出本机，需本机已启动 Ollama",
    },
}


def get_preset(provider: str) -> dict:
    return PROVIDER_PRESETS.get(provider) or PROVIDER_PRESETS[ProviderKind.openai_compat.value]


def requires_key(provider: str) -> bool:
    return bool(get_preset(provider).get("requires_key"))