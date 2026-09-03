"""Durable conversation archive independent from the LLM context history."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError

from bridge.context import Context, _context_value, channel_value, make_conversation_key
from database.db_manager import get_db_manager
from database.models import ConversationRecord
from utils.logger_loguru import get_logger


logger = get_logger("ConversationArchive")

SYSTEM_MESSAGE_TYPES = {
    "auth",
    "mall_system_msg",
    "system_status",
    "system_hint",
    "system_biz",
    "withdraw",
}
SYSTEM_EVENT_TYPES = {
    "auth": "account_authenticated",
    "mall_system_msg": "customer_session_ready",
    "system_status": "system_status",
    "system_hint": "system_notice",
    "system_biz": "system_notice",
    "withdraw": "message_withdrawn",
}


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value or "unknown"))


def _safe_metadata(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return {"value": str(value)}


def _context_raw_data(context: Context) -> Any:
    kwargs = getattr(context, "kwargs", None)
    if kwargs is None:
        return None
    value = getattr(kwargs, "raw_data", None)
    if value is None and isinstance(kwargs, dict):
        value = kwargs.get("raw_data")
    return value


def _content_mapping(content: Any) -> Dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, str) and content:
        try:
            value = json.loads(content)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _message_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp)
        except (ValueError, OSError, OverflowError):
            return datetime.now()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            try:
                return _message_time(float(value))
            except ValueError:
                pass
    return datetime.now()


class ConversationArchiveService:
    """Append and query immutable conversation timeline records."""

    def __init__(self, db_manager=None):
        self.db_manager = db_manager or get_db_manager()

    def append(self, **values: Any) -> Optional[int]:
        record = ConversationRecord(**values)
        session = self.db_manager.get_session()
        try:
            session.add(record)
            session.commit()
            return record.id
        except IntegrityError:
            session.rollback()
            return None
        except Exception as exc:
            session.rollback()
            logger.error(f"对话归档失败: error_type={type(exc).__name__}")
            return None
        finally:
            session.close()

    def _scope_names(self, channel_name: str, shop_id: Any, account_user_id: Any) -> Dict[str, Optional[str]]:
        try:
            shop = self.db_manager.get_shop(str(channel_name), str(shop_id)) or {}
            account = self.db_manager.get_account(
                str(channel_name), str(shop_id), str(account_user_id)
            ) or {}
            return {
                "shop_name": shop.get("shop_name") or None,
                "account_username": account.get("username") or None,
            }
        except Exception:
            return {"shop_name": None, "account_username": None}

    def archive_context(self, context: Context) -> Optional[int]:
        """Archive a message/event received from the channel websocket."""
        from_role = _context_value(context, "from_user")
        to_role = _context_value(context, "to_user")
        is_human_reply = from_role == "mall_cs" or to_role == "user"
        message_type = _enum_value(context.type)
        is_transfer = message_type == "transfer"
        is_system = message_type in SYSTEM_MESSAGE_TYPES
        customer_uid = _context_value(context, "from_uid")
        if is_human_reply and _context_value(context, "to_uid"):
            customer_uid = _context_value(context, "to_uid") or customer_uid
        if message_type == "mall_system_msg":
            customer_uid = str(
                _content_mapping(context.content).get("user_id") or customer_uid
            )
        if message_type == "auth":
            customer_uid = "unknown"

        content = context.content
        metadata = _safe_metadata(_context_raw_data(context))
        if is_transfer:
            transfer_metadata = {
                "from_uid": _context_value(context, "from_uid"),
                "to_uid": _context_value(context, "to_uid"),
            }
            if metadata:
                transfer_metadata["raw_data"] = metadata
            metadata = _safe_metadata(transfer_metadata)

        event_type = SYSTEM_EVENT_TYPES.get(message_type, "message")
        if is_transfer:
            event_type = "transfer"
        if is_transfer:
            # A platform push can describe either direction; preserve the raw
            # roles and use the explicit direction when available.
            event_type = "transfer_to_human" if to_role == "mall_cs" else "transfer"

        return self.append(
            conversation_id=make_conversation_key(context, customer_uid=customer_uid),
            channel_name=channel_value(context.channel_type),
            shop_id=_context_value(context, "shop_id", "unknown"),
            shop_name=_context_value(context, "shop_name") or None,
            account_user_id=_context_value(context, "user_id", "unknown"),
            account_username=_context_value(context, "username") or None,
            customer_uid=customer_uid or "unknown",
            customer_nickname=_context_value(context, "nickname") or None,
            direction=(
                "event"
                if is_transfer or is_system
                else ("outbound" if is_human_reply else "inbound")
            ),
            sender_type=(
                "system"
                if is_transfer or is_system
                else ("human" if is_human_reply else "user")
            ),
            event_type=event_type,
            content=str(content) if content is not None else None,
            platform_message_id=_context_value(context, "msg_id") or None,
            message_type=message_type,
            status=(
                "received"
                if is_system or not is_human_reply
                else "sent"
            ),
            metadata_json=metadata,
            created_at=_message_time(_context_value(context, "timestamp")),
        )

    def reconcile_system_records(self) -> int:
        """Repair legacy system records and attach unambiguous customer scope."""
        session = self.db_manager.get_session()
        updated = 0
        try:
            event_mismatches = [
                and_(
                    ConversationRecord.message_type == message_type,
                    ConversationRecord.event_type != event_type,
                )
                for message_type, event_type in SYSTEM_EVENT_TYPES.items()
            ]
            records = session.query(ConversationRecord).filter(
                ConversationRecord.message_type.in_(SYSTEM_MESSAGE_TYPES),
                or_(
                    ConversationRecord.direction != "event",
                    ConversationRecord.sender_type != "system",
                    ConversationRecord.customer_uid.in_(("", "unknown", "4")),
                    *event_mismatches,
                ),
            ).all()
            customer_cache: Dict[tuple, List[str]] = {}
            for record in records:
                expected_event = SYSTEM_EVENT_TYPES.get(
                    record.message_type, "system_notice"
                )
                customer_uid = None
                if record.message_type == "mall_system_msg":
                    customer_uid = _content_mapping(record.content).get("user_id")
                elif record.message_type == "auth":
                    scope = (
                        record.channel_name,
                        record.shop_id,
                        record.account_user_id,
                    )
                    if scope not in customer_cache:
                        rows = (
                            session.query(ConversationRecord.customer_uid)
                            .filter(
                                ConversationRecord.channel_name == record.channel_name,
                                ConversationRecord.shop_id == record.shop_id,
                                ConversationRecord.account_user_id
                                == record.account_user_id,
                                ConversationRecord.sender_type.in_(
                                    ("user", "ai", "human")
                                ),
                                ConversationRecord.customer_uid.notin_(
                                    ("", "unknown", "4")
                                ),
                            )
                            .distinct()
                            .all()
                        )
                        customer_cache[scope] = [str(row[0]) for row in rows]
                    candidates = customer_cache[scope]
                    if len(candidates) == 1:
                        customer_uid = candidates[0]

                changed = False
                if record.direction != "event":
                    record.direction = "event"
                    changed = True
                if record.sender_type != "system":
                    record.sender_type = "system"
                    changed = True
                if record.event_type != expected_event:
                    record.event_type = expected_event
                    changed = True
                if customer_uid and record.customer_uid != str(customer_uid):
                    record.customer_uid = str(customer_uid)
                    identity = Context.create_pinduoduo_context(
                        shop_id=record.shop_id,
                        user_id=record.account_user_id,
                        from_uid=str(customer_uid),
                        channel_type=record.channel_name,
                    )
                    record.conversation_id = make_conversation_key(identity)
                    changed = True
                if changed:
                    updated += 1
            if updated:
                session.commit()
            return updated
        except Exception as exc:
            session.rollback()
            logger.error(f"系统消息归属修复失败: error_type={type(exc).__name__}")
            return 0
        finally:
            session.close()

    def archive_outbound(
        self, *, channel_name: str, shop_id: Any, account_user_id: Any,
        customer_uid: Any, content: Any, message_type: str,
        sender_type: str, status: str, platform_message_id: Optional[str] = None,
        metadata: Any = None,
    ) -> Optional[int]:
        identity = Context.create_pinduoduo_context(
            shop_id=str(shop_id), user_id=str(account_user_id),
            from_uid=str(customer_uid), channel_type=channel_name,
        )
        names = self._scope_names(channel_name, shop_id, account_user_id)
        return self.append(
            conversation_id=make_conversation_key(identity),
            channel_name=str(channel_name), shop_id=str(shop_id),
            shop_name=names["shop_name"], account_user_id=str(account_user_id),
            account_username=names["account_username"], customer_uid=str(customer_uid),
            direction="outbound", sender_type=sender_type, event_type="message",
            content=str(content) if content is not None else None,
            platform_message_id=platform_message_id, message_type=message_type,
            status=status, metadata_json=_safe_metadata(metadata), created_at=datetime.now(),
        )

    def archive_event(
        self, *, channel_name: str, shop_id: Any, account_user_id: Any,
        customer_uid: Any, event_type: str, status: str, content: Optional[str] = None,
        metadata: Any = None,
    ) -> Optional[int]:
        identity = Context.create_pinduoduo_context(
            shop_id=str(shop_id), user_id=str(account_user_id),
            from_uid=str(customer_uid), channel_type=channel_name,
        )
        names = self._scope_names(channel_name, shop_id, account_user_id)
        return self.append(
            conversation_id=make_conversation_key(identity), channel_name=str(channel_name),
            shop_id=str(shop_id), shop_name=names["shop_name"],
            account_user_id=str(account_user_id), account_username=names["account_username"],
            customer_uid=str(customer_uid), direction="event", sender_type="system",
            event_type=event_type, content=content, message_type="event", status=status,
            metadata_json=_safe_metadata(metadata), created_at=datetime.now(),
        )

    def list_records(
        self, *, channel_name: Optional[str] = None, shop_id: Optional[str] = None,
        account_user_id: Optional[str] = None,
        customer_uid: Optional[str] = None, conversation_id: Optional[str] = None,
        limit: int = 200, offset: int = 0, ascending: bool = False,
    ) -> List[Dict[str, Any]]:
        session = self.db_manager.get_session()
        try:
            query = session.query(ConversationRecord)
            if channel_name:
                query = query.filter(
                    ConversationRecord.channel_name == str(channel_name)
                )
            if shop_id:
                query = query.filter(ConversationRecord.shop_id == str(shop_id))
            if account_user_id:
                query = query.filter(ConversationRecord.account_user_id == str(account_user_id))
            if customer_uid:
                query = query.filter(ConversationRecord.customer_uid == str(customer_uid))
            if conversation_id:
                query = query.filter(
                    ConversationRecord.conversation_id == str(conversation_id)
                )
            ordering = (
                (ConversationRecord.created_at.asc(), ConversationRecord.id.asc())
                if ascending
                else (ConversationRecord.created_at.desc(), ConversationRecord.id.desc())
            )
            records = (
                query.order_by(*ordering)
                .offset(max(0, offset))
                .limit(max(1, min(limit, 2000)))
                .all()
            )
            return [record.to_dict() for record in records]
        finally:
            session.close()

    def list_conversations(
        self, *, shop_id: Optional[str] = None,
        account_user_id: Optional[str] = None, search: Optional[str] = None,
        limit: int = 100, offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return the latest record for each customer conversation."""
        partition = (
            ConversationRecord.channel_name,
            ConversationRecord.shop_id,
            ConversationRecord.customer_uid,
        )
        statement = select(
            ConversationRecord.channel_name,
            ConversationRecord.conversation_id,
            ConversationRecord.shop_id,
            func.max(ConversationRecord.shop_name).over(
                partition_by=partition
            ).label("shop_name"),
            ConversationRecord.account_user_id,
            func.max(ConversationRecord.account_username).over(
                partition_by=partition
            ).label("account_username"),
            ConversationRecord.customer_uid,
            func.max(ConversationRecord.customer_nickname).over(
                partition_by=partition
            ).label("customer_nickname"),
            ConversationRecord.sender_type,
            ConversationRecord.event_type,
            ConversationRecord.message_type,
            ConversationRecord.content,
            ConversationRecord.status,
            ConversationRecord.created_at,
            func.count(ConversationRecord.id).over(
                partition_by=partition
            ).label("message_count"),
            func.row_number().over(
                partition_by=partition,
                order_by=(
                    ConversationRecord.created_at.desc(),
                    ConversationRecord.id.desc(),
                ),
            ).label("record_rank"),
        ).where(
            ConversationRecord.customer_uid.notin_(("", "unknown", "4"))
        )
        if shop_id:
            statement = statement.where(
                ConversationRecord.shop_id == str(shop_id)
            )
        if account_user_id:
            statement = statement.where(
                ConversationRecord.account_user_id == str(account_user_id)
            )
        search_text = str(search or "").strip()
        if search_text:
            pattern = f"%{search_text}%"
            matching_conversations = select(
                ConversationRecord.channel_name,
                ConversationRecord.shop_id,
                ConversationRecord.customer_uid,
            ).where(
                or_(
                    ConversationRecord.customer_uid.like(pattern),
                    ConversationRecord.customer_nickname.like(pattern),
                )
            )
            statement = statement.where(
                tuple_(
                    ConversationRecord.channel_name,
                    ConversationRecord.shop_id,
                    ConversationRecord.customer_uid,
                ).in_(matching_conversations)
            )

        ranked = statement.subquery()
        final_statement = (
            select(ranked)
            .where(ranked.c.record_rank == 1)
            .order_by(ranked.c.created_at.desc(), ranked.c.conversation_id.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500)))
        )
        session = self.db_manager.get_session()
        try:
            rows = session.execute(final_statement).mappings().all()
            conversations = []
            for row in rows:
                item = dict(row)
                item.pop("record_rank", None)
                if item.get("created_at"):
                    item["created_at"] = item["created_at"].isoformat()
                conversations.append(item)
            return conversations
        finally:
            session.close()

    def latest_record_id(self) -> int:
        """Cheap archive revision probe for pollers, served by the primary key."""
        session = self.db_manager.get_session()
        try:
            return int(
                session.execute(
                    select(func.max(ConversationRecord.id))
                ).scalar() or 0
            )
        finally:
            session.close()

    def count_conversations(
        self, *, shop_id: Optional[str] = None,
        account_user_id: Optional[str] = None, search: Optional[str] = None,
    ) -> int:
        """Count customer-grouped conversations without loading their records."""
        statement = select(
            ConversationRecord.channel_name,
            ConversationRecord.shop_id,
            ConversationRecord.customer_uid,
        ).where(
            ConversationRecord.customer_uid.notin_(("", "unknown", "4"))
        )
        if shop_id:
            statement = statement.where(
                ConversationRecord.shop_id == str(shop_id)
            )
        if account_user_id:
            statement = statement.where(
                ConversationRecord.account_user_id == str(account_user_id)
            )
        search_text = str(search or "").strip()
        if search_text:
            pattern = f"%{search_text}%"
            statement = statement.where(
                or_(
                    ConversationRecord.customer_uid.like(pattern),
                    ConversationRecord.customer_nickname.like(pattern),
                )
            )

        session = self.db_manager.get_session()
        try:
            return int(
                session.execute(
                    select(func.count()).select_from(statement.distinct().subquery())
                ).scalar_one()
            )
        finally:
            session.close()


def extract_platform_message_id(result: Any) -> Optional[str]:
    """Extract a platform message id without persisting the whole response."""
    if not isinstance(result, dict):
        return None
    candidates = [result, result.get("result"), result.get("message")]
    nested_result = result.get("result")
    if isinstance(nested_result, dict):
        candidates.append(nested_result.get("message"))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("msg_id", "message_id", "msgId"):
            value = candidate.get(key)
            if value is not None:
                return str(value)
    return None
