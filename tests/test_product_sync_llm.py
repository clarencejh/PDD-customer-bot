from types import SimpleNamespace
import unittest
from unittest import mock

from database.product_sync import ProductSyncService
from utils.llm_provider import LLMProfile, LLMProvider
from utils.llm_transport import NormalizedResponse


class ProductSyncTransportTests(unittest.IsolatedAsyncioTestCase):
    def _service(self):
        return ProductSyncService(object(), request_delay=0)

    def _profile(self):
        return LLMProfile(
            provider=LLMProvider.DEEPSEEK,
            model_name="deepseek-chat",
            api_key="key",
        )

    async def test_product_sync_uses_shared_snapshot_and_preserves_image_json_operation(self):
        service = self._service()
        response = NormalizedResponse('{"brand":"Brand"}', [], {}, object())
        with mock.patch(
            "database.product_sync.async_completion",
            new=mock.AsyncMock(return_value=response),
        ) as completion:
            result = await service._extract_product_knowledge(
                {"goods_name": "Item", "price": "9.9", "sold_quantity": 3, "thumb_url": "https://img.test/item.jpg"},
                {"specifications": [{"name": "size", "value": "M"}]},
                profile=self._profile(),
            )

        self.assertIn("Brand", result)
        self.assertEqual(completion.await_args.args[0].provider, LLMProvider.DEEPSEEK)
        kwargs = completion.await_args.kwargs
        self.assertFalse(kwargs["use_tools"])
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        messages = completion.await_args.args[1]
        self.assertEqual(messages[1]["content"][1]["type"], "image_url")

    async def test_malformed_json_is_returned_unchanged(self):
        service = self._service()
        with mock.patch(
            "database.product_sync.async_completion",
            new=mock.AsyncMock(
                return_value=NormalizedResponse("not-json", [], {}, object())
            ),
        ):
            result = await service._extract_product_knowledge(
                {"goods_name": "Item", "thumb_url": ""},
                {"specifications": []},
                profile=self._profile(),
            )
        self.assertEqual(result, "not-json")

    async def test_provider_failure_falls_back_to_basic_info_without_raw_error(self):
        service = self._service()
        with mock.patch(
            "database.product_sync.async_completion",
            new=mock.AsyncMock(side_effect=RuntimeError("secret-key provider payload")),
        ):
            result = await service._extract_product_knowledge(
                {"goods_name": "Item", "price": "9.9", "sold_quantity": 3},
                {"specifications": [{"name": "size", "value": "M"}]},
                profile=self._profile(),
            )
        self.assertIn("Item", result)
        self.assertNotIn("secret-key", result)

    async def test_missing_profile_keeps_basic_info_fallback(self):
        service = self._service()
        with mock.patch.object(service, "_snapshot_llm_profile", return_value=None):
            result = await service._extract_product_knowledge(
                {"goods_name": "Item", "price": "9.9"},
                {"specifications": []},
            )
        self.assertIn("Item", result)
        self.assertNotIn("async_completion", result)


if __name__ == "__main__":
    unittest.main()
