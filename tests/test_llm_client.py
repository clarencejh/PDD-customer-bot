from types import SimpleNamespace
import unittest
from unittest import mock

from Agent.CustomerAgent.custom import llm_client as client_module
from Agent.CustomerAgent.custom.llm_client import LLMClient
from utils.llm_provider import LLMProfile, LLMProvider
from utils.llm_transport import NormalizedResponse, NormalizedToolCall, NormalizedFunction


class LLMClientContractTests(unittest.IsolatedAsyncioTestCase):
    def _profile(self):
        return LLMProfile(
            provider=LLMProvider.DEEPSEEK,
            model_name="deepseek-chat",
            api_key="key",
        )

    async def test_client_preserves_response_contract_and_per_call_tool_policy(self):
        normalized = NormalizedResponse(
            content="done",
            tool_calls=[
                NormalizedToolCall(
                    id="call-1",
                    function=NormalizedFunction("lookup", '{"id": 1}'),
                )
            ],
            usage={"total_tokens": 3},
            raw_response=SimpleNamespace(),
        )
        with mock.patch.object(
            client_module,
            "async_completion",
            new=mock.AsyncMock(return_value=normalized),
        ) as completion:
            client = LLMClient(profile=self._profile(), temperature=0.2)
            await client.initialize()
            response = await client.chat(
                [{"role": "user", "content": "hello"}],
                use_tools=False,
            )

        self.assertEqual(response.content, "done")
        self.assertEqual(response.tool_calls[0].id, "call-1")
        self.assertEqual(response.usage["total_tokens"], 3)
        completion.assert_awaited_once()
        kwargs = completion.await_args.kwargs
        self.assertFalse(kwargs["use_tools"])
        self.assertEqual(kwargs["tools"], [])

    async def test_legacy_constructor_arguments_remain_usable_with_explicit_provider(self):
        normalized = NormalizedResponse("ok", [], {}, SimpleNamespace())
        with mock.patch.object(
            client_module,
            "async_completion",
            new=mock.AsyncMock(return_value=normalized),
        ) as completion:
            client = LLMClient(
                api_key="key",
                api_base="",
                model_name="deepseek-chat",
                temperature=0.3,
                provider=LLMProvider.DEEPSEEK,
            )
            await client.initialize()
            await client.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(completion.await_args.args[0].provider, LLMProvider.DEEPSEEK)


if __name__ == "__main__":
    unittest.main()
