import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from config import Config, ConfigError
from utils.llm_provider import (
    CapabilityState,
    LLMProvider,
    LLMProfile,
    ProfileValidationError,
    build_llm_profile,
    capability_confirmation_for,
    provider_spec,
    resolve_tool_capability,
)


def _config_payload(**llm_overrides):
    llm = {
        "provider": LLMProvider.OPENAI_COMPATIBLE.value,
        "model_name": "custom-chat",
        "api_key": "test-key",
        "api_base": "https://llm.example.test/v1",
        "endpoint_trust_mode": "explicit",
        "tool_policy": "enabled",
        "capability_confirmation": "",
        "tool_trust_confirmation": "",
    }
    llm.update(llm_overrides)
    return {
        "llm": llm,
        "business_hours": {"start": "08:00", "end": "23:00"},
        "prompt": {"instructions": []},
        "db_path": "./temp/channel_shop.db",
    }


class ProviderRegistryTests(unittest.TestCase):
    def test_all_built_in_routes_are_explicit_and_portable(self):
        expected = {
            LLMProvider.DEEPSEEK: "deepseek/",
            LLMProvider.VOLCENGINE: "volcengine/",
            LLMProvider.OPENAI_COMPATIBLE: "openai/",
            LLMProvider.KIMI: "moonshot/",
            LLMProvider.ZHIPU: "zai/",
            LLMProvider.QWEN: "dashscope/",
        }

        for provider, prefix in expected.items():
            spec = provider_spec(provider)
            self.assertEqual(spec.litellm_prefix, prefix)
            profile_data = _config_payload(
                provider=provider.value,
                model_name="model-without-provider-guessing",
                api_base="https://provider.example.test/v1",
                endpoint_trust_mode="explicit",
            )
            profile_data["llm"]["capability_confirmation"] = capability_confirmation_for(
                profile_data["llm"]
            )
            profile_data["llm"]["tool_trust_confirmation"] = capability_confirmation_for(
                profile_data["llm"]
            )
            profile = build_llm_profile(profile_data["llm"], require_confirmation=False)
            self.assertEqual(profile.route_model, prefix + profile.model_name)


class CapabilityPolicyTests(unittest.TestCase):
    def test_capability_policy_has_supported_unsupported_and_unknown_states(self):
        supported = build_llm_profile(
            {
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "api_key": "key",
                "api_base": "",
                "tool_policy": "enabled",
            },
            require_confirmation=False,
        )
        unsupported = LLMProfile(
            provider=LLMProvider.DEEPSEEK,
            model_name="text-embedding-3-small",
            api_key="key",
        )
        unknown = build_llm_profile(
            {
                "provider": "openai_compatible",
                "model_name": "vendor-private-chat",
                "api_key": "key",
                "api_base": "https://llm.example.test/v1",
                "endpoint_trust_mode": "explicit",
                "tool_policy": "enabled",
            },
            require_confirmation=False,
        )

        self.assertEqual(resolve_tool_capability(supported).state, CapabilityState.SUPPORTED)
        self.assertEqual(resolve_tool_capability(unsupported).state, CapabilityState.UNSUPPORTED)
        self.assertEqual(resolve_tool_capability(unknown).state, CapabilityState.UNKNOWN)

    def test_unknown_capability_requires_exact_current_profile_confirmation(self):
        data = _config_payload()
        with self.assertRaises(ProfileValidationError) as raised:
            build_llm_profile(data["llm"])
        self.assertEqual(raised.exception.code, "capability_confirmation_required")

        data["llm"]["capability_confirmation"] = capability_confirmation_for(data["llm"])
        data["llm"]["tool_trust_confirmation"] = capability_confirmation_for(data["llm"])
        profile = build_llm_profile(data["llm"])
        self.assertEqual(resolve_tool_capability(profile).state, CapabilityState.UNKNOWN)

        changed = dict(data["llm"], model_name="another-private-chat")
        with self.assertRaises(ProfileValidationError) as changed_error:
            build_llm_profile(changed)
        self.assertEqual(changed_error.exception.code, "capability_confirmation_required")

    def test_known_unsupported_model_fails_closed(self):
        with self.assertRaises(ProfileValidationError) as raised:
            build_llm_profile(
                {
                    "provider": "deepseek",
                    "model_name": "text-embedding-3-small",
                    "api_key": "key",
                    "tool_policy": "enabled",
                }
            )
        self.assertEqual(raised.exception.code, "unsupported_tool_capability")
        self.assertIn("deepseek", raised.exception.safe_message.lower())
        self.assertIn("text-embedding-3-small", raised.exception.safe_message)


class ConfigMigrationTests(unittest.TestCase):
    def _write(self, path: Path, payload: dict):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_legacy_ark_config_is_migrated_to_volcengine_and_key_is_protected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            payload = _config_payload(
                provider=None,
                model_name="ark-code-latest",
                api_key="legacy-key",
                api_base="https://ark.cn-beijing.volces.com/api/plan/v3",
            )
            payload["llm"].pop("provider")
            payload["llm"].pop("endpoint_trust_mode")
            payload["llm"].pop("tool_policy")
            payload["llm"].pop("capability_confirmation")
            payload["llm"].pop("tool_trust_confirmation")
            self._write(path, payload)

            manager = Config(path, auto_create=False)
            self.assertEqual(manager.get("llm.provider"), LLMProvider.VOLCENGINE.value)
            self.assertEqual(manager.get("llm.model_name"), "ark-code-latest")
            self.assertEqual(manager.get("llm.api_base"), payload["llm"]["api_base"])
            self.assertEqual(manager.get("llm.api_key"), "legacy-key")

            persisted = json.loads(path.read_text(encoding="utf-8"))
            if os.name == "nt":
                self.assertTrue(persisted["llm"]["api_key"].startswith("dpapi:v1:"))
            self.assertEqual(persisted["llm"]["provider"], "volcengine")

    def test_unknown_legacy_endpoint_is_migrated_to_openai_compatible(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            payload = _config_payload(
                model_name="custom-model",
                api_key="legacy-key",
                api_base="https://custom.example.test/v1",
            )
            payload["llm"].pop("provider")
            self._write(path, payload)

            manager = Config(path, auto_create=False)
            self.assertEqual(
                manager.get("llm.provider"), LLMProvider.OPENAI_COMPATIBLE.value
            )
            self.assertEqual(manager.get("llm.model_name"), "custom-model")
            self.assertEqual(manager.get("llm.api_base"), "https://custom.example.test/v1")

    def test_false_save_restores_memory_and_keeps_file_unchanged(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            payload = _config_payload(
                provider="deepseek",
                model_name="deepseek-chat",
                api_base="",
                endpoint_trust_mode="default",
            )
            self._write(path, payload)
            manager = Config(path, auto_create=False)
            before_file = path.read_bytes()
            before_model = manager.get("llm.model_name")

            with mock.patch.object(manager, "save", return_value=False):
                with self.assertRaises(ConfigError):
                    manager.update({"llm": {"model_name": "new-model"}}, save=True)

            self.assertEqual(manager.get("llm.model_name"), before_model)
            self.assertEqual(path.read_bytes(), before_file)


if __name__ == "__main__":
    unittest.main()
