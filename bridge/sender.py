"""回复发送抽象层。

Message/Agent 层通过本模块获取发送器，避免直接 import 具体渠道（如拼多多），
使处理器链与工具保持渠道无关。新增渠道时实现 ReplySender 并在 _SENDERS 注册。

各发送方法均为同步阻塞调用（HTTP），调用方应在工作线程中执行
（如 asyncio.to_thread）以避免阻塞事件循环。
"""
from __future__ import annotations

from typing import Any, Optional

from bridge.context import ChannelType


class ReplySender:
    """回复发送器抽象基类（传输层）。"""

    def send_text(self, shop_id, user_id, recipient_uid, text: str, sender_type: str = "human") -> Any:
        raise NotImplementedError

    def send_image(self, shop_id, user_id, recipient_uid, image_url: str, sender_type: str = "human") -> Any:
        raise NotImplementedError

    def send_product_card(self, shop_id, user_id, recipient_uid, goods_id, biz_type: int = 2, sender_type: str = "human") -> Any:
        raise NotImplementedError

    def get_cs_list(self, shop_id, user_id) -> Optional[dict]:
        raise NotImplementedError

    def transfer_to_cs(self, shop_id, user_id, recipient_uid, cs_uid) -> Any:
        raise NotImplementedError

    def transfer_to_ai(self, shop_id, user_id, recipient_uid, ai_uid=None) -> Any:
        raise NotImplementedError


class PinduoduoSender(ReplySender):
    """拼多多发送器，封装现有 SendMessage。"""

    @staticmethod
    def _archive(shop_id, user_id, recipient_uid, content, message_type, sender_type, result):
        from database.conversation_archive import (
            ConversationArchiveService,
            extract_platform_message_id,
        )
        success = isinstance(result, dict) and result.get("success") is True
        ConversationArchiveService().archive_outbound(
            channel_name=ChannelType.PINDUODUO.value,
            shop_id=shop_id,
            account_user_id=user_id,
            customer_uid=recipient_uid,
            content=content,
            message_type=message_type,
            sender_type=sender_type,
            status="sent" if success else "failed",
            platform_message_id=extract_platform_message_id(result),
        )

    def send_text(self, shop_id, user_id, recipient_uid, text, sender_type="human"):
        from Channel.pinduoduo.utils.API.send_message import SendMessage
        try:
            result = SendMessage(str(shop_id), str(user_id)).send_text(recipient_uid, text)
        except Exception:
            self._archive(shop_id, user_id, recipient_uid, text, "text", sender_type, None)
            raise
        self._archive(shop_id, user_id, recipient_uid, text, "text", sender_type, result)
        return result

    def send_image(self, shop_id, user_id, recipient_uid, image_url, sender_type="human"):
        from Channel.pinduoduo.utils.API.send_message import SendMessage
        try:
            result = SendMessage(str(shop_id), str(user_id)).send_image(recipient_uid, image_url)
        except Exception:
            self._archive(shop_id, user_id, recipient_uid, image_url, "image", sender_type, None)
            raise
        self._archive(shop_id, user_id, recipient_uid, image_url, "image", sender_type, result)
        return result

    def send_product_card(self, shop_id, user_id, recipient_uid, goods_id, biz_type=2, sender_type="human"):
        from Channel.pinduoduo.utils.API.send_message import SendMessage
        try:
            result = SendMessage(str(shop_id), str(user_id)).send_mallGoodsCard(
                recipient_uid, goods_id, biz_type
            )
        except Exception:
            self._archive(shop_id, user_id, recipient_uid, goods_id, "goods_card", sender_type, None)
            raise
        self._archive(shop_id, user_id, recipient_uid, goods_id, "goods_card", sender_type, result)
        return result

    def get_cs_list(self, shop_id, user_id):
        from Channel.pinduoduo.utils.API.send_message import SendMessage
        return SendMessage(str(shop_id), str(user_id)).getAssignCsList()

    def transfer_to_cs(self, shop_id, user_id, recipient_uid, cs_uid):
        from Channel.pinduoduo.utils.API.send_message import SendMessage
        try:
            result = SendMessage(str(shop_id), str(user_id)).move_conversation(
                recipient_uid, cs_uid
            )
        except Exception:
            self._archive_transfer_event(
                shop_id, user_id, recipient_uid, "transfer_to_human", "failed",
                f"转接至客服 {cs_uid}", {"target_cs_uid": str(cs_uid)},
            )
            raise
        self._archive_transfer_event(
            shop_id, user_id, recipient_uid, "transfer_to_human",
            "sent" if isinstance(result, dict) and result.get("success") is True else "failed",
            f"转接至客服 {cs_uid}", {"target_cs_uid": str(cs_uid)},
        )
        return result

    @staticmethod
    def _archive_transfer_event(
        shop_id, user_id, recipient_uid, event_type, status, content, metadata
    ):
        from database.conversation_archive import ConversationArchiveService
        ConversationArchiveService().archive_event(
            channel_name=ChannelType.PINDUODUO.value,
            shop_id=shop_id,
            account_user_id=user_id,
            customer_uid=recipient_uid,
            event_type=event_type,
            status=status,
            content=content,
            metadata=metadata,
        )

    def transfer_to_ai(self, shop_id, user_id, recipient_uid, ai_uid=None):
        """Move a conversation back to the current account's AI identity."""
        from Channel.pinduoduo.utils.API.send_message import SendMessage
        target_uid = str(ai_uid or f"cs_{shop_id}_{user_id}")
        try:
            result = SendMessage(str(shop_id), str(user_id)).move_conversation(
                recipient_uid, target_uid
            )
        except Exception:
            self._archive_transfer_event(
                shop_id, user_id, recipient_uid, "transfer_to_ai", "failed",
                "转回 AI", {"target_ai_uid": target_uid},
            )
            raise
        self._archive_transfer_event(
            shop_id, user_id, recipient_uid, "transfer_to_ai",
            "sent" if isinstance(result, dict) and result.get("success") is True else "failed",
            "转回 AI", {"target_ai_uid": target_uid},
        )
        return result


# 渠道 -> 发送器 注册表
_SENDERS = {
    ChannelType.PINDUODUO: PinduoduoSender(),
}


def get_sender(channel_type=None) -> Optional[ReplySender]:
    """获取指定渠道的发送器。

    channel_type 为 None 或未注册时，回退到默认渠道（拼多多，当前唯一渠道）。
    """
    if channel_type is not None:
        ct = channel_type if isinstance(channel_type, ChannelType) else ChannelType(str(channel_type))
        if ct in _SENDERS:
            return _SENDERS[ct]
    return _SENDERS.get(ChannelType.PINDUODUO)
