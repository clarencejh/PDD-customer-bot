import os
import unittest

from PyQt6.QtWidgets import QApplication

from ui.setting_ui import LLMConfigCard, inspect_llm_draft
from utils.llm_provider import capability_confirmation_for


class SettingPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_card_exposes_exactly_six_providers_and_round_trips_values(self):
        card = LLMConfigCard()
        values = card._provider_values
        self.assertEqual(
            values,
            ["deepseek", "volcengine", "openai_compatible", "kimi", "zhipu", "qwen"],
        )
        source = {
            "provider": "openai_compatible",
            "model_name": "vendor-private-model",
            "api_key": "key",
            "api_base": "https://llm.example.test/v1",
            "endpoint_trust_mode": "explicit",
            "tool_policy": "enabled",
        }
        card.setConfig(source)
        self.assertEqual(card.getConfig()["provider"], "openai_compatible")
        self.assertEqual(card.getConfig()["model_name"], "vendor-private-model")
        self.assertEqual(card.getConfig()["api_base"], "https://llm.example.test/v1")

    def test_provider_switch_preserves_typed_values_until_explicit_reset(self):
        card = LLMConfigCard()
        card.setConfig(
            {
                "provider": "deepseek",
                "model_name": "my-deepseek-model",
                "api_key": "key",
                "api_base": "https://custom.example.test/v1",
            }
        )
        card.provider_combo.setCurrentIndex(card._provider_values.index("qwen"))
        self.assertEqual(card.model_name_edit.text(), "my-deepseek-model")
        self.assertEqual(card.api_base_edit.text(), "https://custom.example.test/v1")
        card.reset_to_provider_default()
        self.assertEqual(card.api_base_edit.text(), "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(card.model_name_edit.text(), "qwen-plus")

    def test_unknown_capability_is_unverified_until_exact_fingerprint_is_present(self):
        draft = {
            "provider": "openai_compatible",
            "model_name": "vendor-private-model",
            "api_key": "key",
            "api_base": "https://llm.example.test/v1",
            "endpoint_trust_mode": "explicit",
            "tool_policy": "enabled",
        }
        state = inspect_llm_draft(draft)
        self.assertEqual(state["state"], "unknown")
        self.assertTrue(state["requires_confirmation"])
        fingerprint = state["fingerprint"]
        draft["capability_confirmation"] = fingerprint
        draft["tool_trust_confirmation"] = fingerprint
        confirmed = inspect_llm_draft(draft)
        self.assertFalse(confirmed["requires_confirmation"])

    def test_known_unsupported_capability_is_blocked_without_confirmation_prompt(self):
        state = inspect_llm_draft(
            {
                "provider": "deepseek",
                "model_name": "text-embedding-3-small",
                "api_key": "key",
            }
        )
        self.assertEqual(state["state"], "unsupported")
        self.assertIn("embedding", state["error"].safe_message)


if __name__ == "__main__":
    unittest.main()
