import asyncio
from types import SimpleNamespace
import unittest
from unittest import mock

from utils import llm_transport as transport
from utils.llm_provider import (
    EndpointTrustMode,
    LLMProfile,
    LLMProvider,
    capability_confirmation_for,
)


def _profile(
    provider=LLMProvider.DEEPSEEK,
    model_name="deepseek-chat",
    api_base="",
    endpoint_trust_mode=EndpointTrustMode.DEFAULT,
    confirmations=True,
):
    profile = LLMProfile(
        provider=provider,
        model_name=model_name,
        api_key="secret-key",
        api_base=api_base,
        endpoint_trust_mode=endpoint_trust_mode,
    )
    if confirmations:
        fingerprint = capability_confirmation_for(profile)
        profile = LLMProfile(
            **{
                **profile.__dict__,
                "capability_confirmation": fingerprint,
                "tool_trust_confirmation": fingerprint,
            }
        )
    return profile


class _FakeLiteLLM:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response
        self.error = error

    async def acompletion(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _response(content="ok", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(total_tokens=7, prompt_tokens=4, completion_tokens=3),
    )


class TransportPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_tools_payload_has_no_legacy_nonportable_defaults(self):
        fake = _FakeLiteLLM(_response("answer"))
        with mock.patch.object(transport, "litellm", fake):
            await transport.async_completion(
                _profile(),
                [{"role": "user", "content": "hello"}],
                tools=[{"type": "function", "function": {"name": "lookup"}}],
                tool_choice="auto",
                use_tools=True,
            )

        payload = fake.calls[0]
        self.assertEqual(payload["model"], "deepseek/deepseek-chat")
        self.assertIn("tools", payload)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertNotIn("logprobs", payload)
        self.assertNotIn("top_logprobs", payload)
        self.assertNotIn("extra_body", payload)

    async def test_six_provider_routes_keep_raw_model_names(self):
        cases = [
            (LLMProvider.DEEPSEEK, "deepseek-chat", "deepseek/deepseek-chat"),
            (LLMProvider.VOLCENGINE, "ark-code-latest", "volcengine/ark-code-latest"),
            (LLMProvider.OPENAI_COMPATIBLE, "gpt-4o", "openai/gpt-4o"),
            (LLMProvider.KIMI, "moonshot-v1-8k", "moonshot/moonshot-v1-8k"),
            (LLMProvider.ZHIPU, "glm-4", "zai/glm-4"),
            (LLMProvider.QWEN, "qwen-plus", "dashscope/qwen-plus"),
        ]
        for provider, model_name, route in cases:
            fake = _FakeLiteLLM(_response())
            api_base = "https://llm.example.test/v1" if provider is LLMProvider.OPENAI_COMPATIBLE else ""
            dns_patch = mock.patch.object(
                transport.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            )
            with mock.patch.object(transport, "litellm", fake), dns_patch:
                await transport.async_completion(
                    _profile(provider, model_name, api_base, EndpointTrustMode.EXPLICIT),
                    [{"role": "user", "content": "hello"}],
                    use_tools=True,
                )
            self.assertEqual(fake.calls[0]["model"], route)
            self.assertEqual(fake.calls[0]["api_key"], "secret-key")
            if api_base:
                self.assertEqual(fake.calls[0]["base_url"], api_base)
            else:
                self.assertNotIn("base_url", fake.calls[0])

    async def test_custom_openai_compatible_endpoint_passes_only_explicit_endpoint(self):
        profile = _profile(
            LLMProvider.OPENAI_COMPATIBLE,
            "vendor-private-model",
            "https://llm.example.test/v1",
            EndpointTrustMode.EXPLICIT,
        )
        fake = _FakeLiteLLM(_response())
        public_dns = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with mock.patch.object(transport, "litellm", fake), mock.patch.object(
            transport.socket, "getaddrinfo", return_value=public_dns
        ):
            await transport.async_completion(
                profile,
                [{"role": "user", "content": "hello"}],
                use_tools=True,
            )
        payload = fake.calls[0]
        self.assertEqual(payload["model"], "openai/vendor-private-model")
        self.assertEqual(payload["base_url"], "https://llm.example.test/v1")
        self.assertNotIn("provider", payload)
        self.assertNotIn("api_base", payload)

    async def test_no_tool_operation_omits_tool_fields_and_preserves_scoped_json(self):
        fake = _FakeLiteLLM(_response('{"ok": true}'))
        with mock.patch.object(transport, "litellm", fake):
            await transport.async_completion(
                _profile(),
                [
                    {"role": "system", "content": "extract"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "item"},
                            {"type": "image_url", "image_url": {"url": "https://img.test/a.jpg"}},
                        ],
                    },
                ],
                use_tools=False,
                response_format={"type": "json_object"},
            )
        payload = fake.calls[0]
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"][1]["content"][1]["type"], "image_url")

    async def test_runtime_clients_disable_redirects_for_deepseek_and_compatible_routes(self):
        cases = [
            (_profile(LLMProvider.DEEPSEEK), None),
            (
                _profile(
                    LLMProvider.OPENAI_COMPATIBLE,
                    "vendor-model",
                    "https://llm.example.test/v1",
                    EndpointTrustMode.EXPLICIT,
                ),
                [(2, 1, 6, "", ("93.184.216.34", 443))],
            ),
        ]
        for profile, dns_result in cases:
            fake = _FakeLiteLLM(_response())
            dns_patch = mock.patch.object(
                transport.socket,
                "getaddrinfo",
                return_value=dns_result,
            ) if dns_result is not None else mock.patch.object(
                transport.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            )
            with mock.patch.object(transport, "litellm", fake), dns_patch:
                await transport.async_completion(
                    profile,
                    [{"role": "user", "content": "hello"}],
                    use_tools=False,
                )

            client = fake.calls[0]["client"]
            if profile.provider is LLMProvider.DEEPSEEK:
                self.assertFalse(client.client.follow_redirects)
            else:
                self.assertFalse(client._client.follow_redirects)


class ResponseAndErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_normalization_preserves_tool_call_and_usage(self):
        tool_call = SimpleNamespace(
            id="call-1",
            type="function",
            function=SimpleNamespace(name="lookup", arguments='{"id": 1}'),
        )
        fake = _FakeLiteLLM(_response("thinking", [tool_call]))
        with mock.patch.object(transport, "litellm", fake):
            normalized = await transport.async_completion(
                _profile(),
                [{"role": "user", "content": "lookup"}],
                tools=[{"type": "function"}],
                use_tools=True,
            )
        self.assertEqual(normalized.content, "thinking")
        self.assertEqual(normalized.tool_calls[0].id, "call-1")
        self.assertEqual(normalized.tool_calls[0].function.name, "lookup")
        self.assertEqual(normalized.tool_calls[0].function.arguments, '{"id": 1}')
        self.assertEqual(normalized.usage["total_tokens"], 7)

    async def test_error_categories_are_distinct_and_safe(self):
        errors = [
            (transport.LLMErrorCategory.AUTHENTICATION, transport.AuthenticationError("secret-key")),
            (transport.LLMErrorCategory.RATE_LIMIT, transport.RateLimitError("secret-key")),
            (transport.LLMErrorCategory.TOOL_CAPABILITY, ValueError("unsupported tool parameter")),
        ]
        for category, error in errors:
            fake = _FakeLiteLLM(error=error)
            with mock.patch.object(transport, "litellm", fake):
                with self.assertRaises(transport.LLMTransportError) as raised:
                    await transport.async_completion(
                        _profile(),
                        [{"role": "user", "content": "hello"}],
                        use_tools=False,
                    )
            self.assertEqual(raised.exception.category, category)
            self.assertNotIn("secret-key", str(raised.exception))
            self.assertNotIn("secret-key", raised.exception.safe_message)


class EndpointPolicyTests(unittest.TestCase):
    def test_endpoint_rejects_credentials_metadata_and_cross_host_redirects(self):
        with self.assertRaises(transport.EndpointPolicyError):
            transport.validate_transport_endpoint(
                _profile(
                    LLMProvider.OPENAI_COMPATIBLE,
                    "gpt-4o",
                    "https://user:pass@llm.example.test/v1",
                    EndpointTrustMode.EXPLICIT,
                )
            )

        with mock.patch.object(
            transport.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("169.254.169.254", 443))],
        ):
            with self.assertRaises(transport.EndpointPolicyError):
                transport.validate_transport_endpoint(
                    _profile(
                        LLMProvider.OPENAI_COMPATIBLE,
                        "gpt-4o",
                        "https://metadata.example.test/v1",
                        EndpointTrustMode.EXPLICIT,
                    )
                )

        with self.assertRaises(transport.EndpointPolicyError):
            transport.validate_redirect_origin(
                "https://llm.example.test/v1",
                "https://evil.example.test/v1",
            )

    def test_local_endpoint_requires_explicit_local_opt_in(self):
        with self.assertRaises(transport.EndpointPolicyError):
            transport.validate_transport_endpoint(
                _profile(
                    LLMProvider.OPENAI_COMPATIBLE,
                    "gpt-4o",
                    "https://127.0.0.1:8080/v1",
                    EndpointTrustMode.EXPLICIT,
                )
            )
        profile = _profile(
            LLMProvider.OPENAI_COMPATIBLE,
            "gpt-4o",
            "https://127.0.0.1:8080/v1",
            EndpointTrustMode.LOCAL,
        )
        self.assertEqual(transport.validate_transport_endpoint(profile), profile.api_base)

    def test_local_http_endpoint_allowed_only_with_local_opt_in(self):
        with self.assertRaises(transport.EndpointPolicyError):
            transport.validate_transport_endpoint(
                _profile(
                    LLMProvider.OPENAI_COMPATIBLE,
                    "qwen2.5",
                    "http://127.0.0.1:11434/v1",
                    EndpointTrustMode.EXPLICIT,
                )
            )

        http_remote = _profile(
            LLMProvider.OPENAI_COMPATIBLE,
            "gpt-4o",
            "http://llm.example.test/v1",
            EndpointTrustMode.EXPLICIT,
        )
        with self.assertRaises(transport.EndpointPolicyError):
            transport.validate_transport_endpoint(http_remote)

        for base in ("http://127.0.0.1:11434/v1", "http://192.168.1.20:8080/v1"):
            profile = _profile(
                LLMProvider.OPENAI_COMPATIBLE,
                "qwen2.5",
                base,
                EndpointTrustMode.LOCAL,
            )
            self.assertEqual(transport.validate_transport_endpoint(profile), profile.api_base)


if __name__ == "__main__":
    unittest.main()
