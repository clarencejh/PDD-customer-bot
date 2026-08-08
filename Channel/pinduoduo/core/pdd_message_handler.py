"""Pinduoduo message conversion and account-scoped dispatch."""

from __future__ import annotations

import asyncio
import json

from bridge.context import ChannelType, Context, ContextType
from Channel.pinduoduo.pdd_message import PDDChatMessage
from database import db_manager
from utils.logger_loguru import get_logger


class MessageHandlerMixin:
    async def _setup_message_consumer(
        self,
        queue_name: str,
        shop_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Create one consumer and one Agent for this PDDChannel/account."""
        from Message import handler_chain
        from Agent.CustomerAgent.custom.customer_agent import CustomerAgent
        from core.di_container import container, configure_standard_services

        try:
            existing_consumer = self.consumer_manager.get_consumer(queue_name)
            if existing_consumer is not None:
                await self.consumer_manager.stop_consumer(queue_name, remove=True)
                self.queue_manager.remove_queue(queue_name)

            consumer = self.consumer_manager.create_consumer(
                queue_name,
                max_concurrent=10,
            )
            if self._account_agent is None:
                if not container.is_registered(CustomerAgent):
                    configure_standard_services()
                self._account_agent = container.get(CustomerAgent)

            handlers = handler_chain(
                use_ai=True,
                business_hours=self.business_hours,
                bot=self._account_agent,
                ai_failure_callback=getattr(self, "ai_failure_callback", None),
            )
            for handler in handlers:
                consumer.add_handler(handler)

            await self.consumer_manager.start_consumer(queue_name)
            self.logger.debug(f"message consumer started: {queue_name}")
        except Exception as exc:
            self.logger.error(
                f"message consumer setup failed: error_type={type(exc).__name__}"
            )
            raise

    async def _process_websocket_message(
        self,
        message: str,
        shop_id: str,
        user_id: str,
        username: str,
        queue_name: str,
    ) -> None:
        try:
            if not message or not message.strip():
                return

            message_data = json.loads(message)
            msg_type = message_data.get("message", {}).get("type", "unknown")
            self.logger.debug(
                f"received message: type={msg_type}, shop_id={shop_id}"
            )

            pdd_message = PDDChatMessage(message_data)
            context = await asyncio.to_thread(
                self._convert_to_context, pdd_message, shop_id, user_id, username
            )
            if not context:
                return

            if self._should_process_immediately(context):
                await self._handle_immediate_message(context, shop_id, user_id)
            elif self._should_queue_message(context):
                msg_id = await self.queue_manager.get_or_create_queue(queue_name).put(
                    context
                )
                self.logger.debug(
                    f"message queued: {queue_name}, ID: {msg_id}, type: {context.type}"
                )
        except json.JSONDecodeError:
            self.logger.error("invalid websocket JSON message")
        except Exception as exc:
            self.logger.error(
                f"websocket message handling failed: error_type={type(exc).__name__}"
            )

    def _should_process_immediately(self, context: Context) -> bool:
        return context.type in {
            ContextType.SYSTEM_STATUS,
            ContextType.AUTH,
            ContextType.WITHDRAW,
            ContextType.SYSTEM_HINT,
            ContextType.MALL_CS,
            ContextType.TRANSFER,
        }

    def _should_queue_message(self, context: Context) -> bool:
        return context.type in {
            ContextType.TEXT,
            ContextType.IMAGE,
            ContextType.VIDEO,
            ContextType.EMOTION,
            ContextType.GOODS_INQUIRY,
            ContextType.ORDER_INFO,
            ContextType.GOODS_CARD,
            ContextType.GOODS_SPEC,
        }

    async def _handle_immediate_message(
        self,
        context: Context,
        shop_id: str,
        user_id: str,
    ) -> None:
        """Handle system messages without blocking the event loop."""
        kwargs = context.kwargs
        username = getattr(kwargs, "username", None)
        recipient_uid = getattr(kwargs, "from_uid", None)
        if isinstance(kwargs, dict):
            username = username or kwargs.get("username")
            recipient_uid = recipient_uid or kwargs.get("from_uid")
        username = username or ""
        recipient_uid = recipient_uid or ""
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            def _send_notice():
                SendMessage(shop_id, user_id).send_text(recipient_uid, "[玫瑰]")
            if context.type == ContextType.AUTH:
                auth_info = context.content
                if isinstance(auth_info, dict):
                    self.logger.info(
                        f"{username} auth result: {auth_info.get('result')}"
                    )
            elif context.type == ContextType.WITHDRAW:
                await asyncio.to_thread(
                    _send_notice
                )
            elif context.type == ContextType.TRANSFER:
                await asyncio.to_thread(
                    _send_notice
                )
            else:
                self.logger.debug(f"system message: {context.type}")
        except Exception as exc:
            self.logger.error(
                f"immediate message handling failed: error_type={type(exc).__name__}"
            )

    def _convert_to_context(
        self,
        pdd_message: PDDChatMessage,
        shop_id: str,
        user_id: str,
        username: str,
    ) -> Context:
        shop_info = db_manager.get_shop(self.channel_name, shop_id) or {}
        shop_name = shop_info.get("shop_name", "")
        content = pdd_message.content
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        elif content is None:
            content = ""
        else:
            content = str(content)

        return Context.create_pinduoduo_context(
            content=content,
            msg_id=str(pdd_message.msg_id) if pdd_message.msg_id is not None else "",
            from_user=str(pdd_message.from_user or ""),
            from_uid=str(pdd_message.from_uid or ""),
            to_user=str(pdd_message.to_user or ""),
            to_uid=str(pdd_message.to_uid or ""),
            nickname=str(pdd_message.nickname or ""),
            timestamp=pdd_message.timestamp,
            user_msg_type=pdd_message.user_msg_type,
            shop_id=str(shop_id),
            user_id=str(user_id),
            username=str(username),
            shop_name=str(shop_name),
            raw_data=pdd_message.raw_data,
            channel_type=ChannelType.PINDUODUO,
        )


__all__ = ["MessageHandlerMixin"]
