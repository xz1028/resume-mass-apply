"""磐古大模型预设测试（tasks 3.3）：三处清单一致性 + 零内置 Key 红线。"""

from app.ai.llm.presets import PROVIDER_PRESETS, get_preset, requires_key
from app.ai.models import ProviderKind


class TestPanguPreset:
    def test_enum_contains_pangu(self):
        assert ProviderKind.pangu.value == "pangu"

    def test_preset_five_fields_structure(self):
        preset = PROVIDER_PRESETS["pangu"]
        assert set(preset) == {"label", "base_url", "requires_key", "default_model", "note"}
        assert preset["label"] == "华为云磐古大模型"
        assert preset["base_url"].startswith("https://")
        assert preset["requires_key"] is True
        assert preset["default_model"] == "pangu-nlp"
        assert "ModelArts" in preset["note"]
        assert "自带 Key" in preset["note"]

    def test_get_pangu_preset_no_fallback(self):
        preset = get_preset("pangu")
        assert preset is PROVIDER_PRESETS["pangu"]  # 不回退 openai_compat

    def test_requires_key_pangu(self):
        assert requires_key("pangu") is True

    def test_preset_has_no_builtin_key(self):
        """红线：预设定义不含任何密钥值（spec 5.7.1.1b）。"""
        for provider, preset in PROVIDER_PRESETS.items():
            for key in ("api_key", "key", "token", "secret"):
                assert key not in preset, f"{provider} 预设含密钥字段 {key}"

    def test_existing_providers_unchanged(self):
        """既有 6 个 provider 条目行为不变。"""
        expected = {"deepseek", "qwen", "kimi", "zhipu", "openai_compat", "ollama"}
        assert expected <= set(PROVIDER_PRESETS)
        assert PROVIDER_PRESETS["deepseek"]["default_model"] == "deepseek-chat"
        assert requires_key("ollama") is False

    def test_frontend_backend_list_consistency(self):
        """三处清单（枚举/后端预设/前端数组）一致性：前端数组含磐古行。"""
        import re
        from pathlib import Path

        source = Path("app/static/js/views/ai-config-page.js").read_text(encoding="utf-8")
        providers_block = re.search(r"const providers = \[(.*?)\];", source, re.DOTALL)
        assert providers_block, "前端 providers 数组未找到"
        body = providers_block.group(1)
        values = re.findall(r"value:\s*'([a-z_]+)'", body)
        assert set(values) == set(PROVIDER_PRESETS.keys()), (
            f"前后端清单不一致: {set(values) ^ set(PROVIDER_PRESETS.keys())}"
        )
        assert "华为云磐古大模型" in body
        assert "pangu-nlp" in body