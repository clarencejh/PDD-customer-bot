"""SQLAlchemy models for channel, account and knowledge data."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    shops = relationship("Shop", back_populates="channel", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Channel(channel_name='{self.channel_name}')>"


class Shop(Base):
    __tablename__ = "shops"
    __table_args__ = (
        UniqueConstraint("channel_id", "shop_id", name="uix_shop_channel_shop"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    shop_id = Column(String(100), nullable=False)
    shop_name = Column(String(100), nullable=False)
    shop_logo = Column(String(255), nullable=True)
    description = Column(String(255))
    channel = relationship("Channel", back_populates="shops")
    accounts = relationship("Account", back_populates="shop", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Shop(shop_id='{self.shop_id}', shop_name='{self.shop_name}')>"


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("shop_id", "user_id", name="uix_account_shop_user"),
        UniqueConstraint("shop_id", "username", name="uix_account_shop_username"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    user_id = Column(String(100), nullable=False)
    username = Column(String(100), nullable=False)
    # Stored as a DPAPI-protected value on Windows; legacy plaintext rows are
    # still readable for backwards compatibility.
    password = Column(String(255), nullable=False)
    cookies = Column(Text)
    status = Column(Integer, default=None)
    # True=店铺主账号，False=客服子账号，None=尚未完成身份识别
    is_main_account = Column(Boolean, nullable=True, default=None)
    shop = relationship("Shop", back_populates="accounts")

    def __repr__(self):
        return f"<Account(username='{self.username}')>"


class Keyword(Base):
    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("keyword", name="uix_keyword_keyword"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(String(100), nullable=False)

    def __repr__(self):
        return f"<Keyword(keyword='{self.keyword}')>"


class ProductKnowledge(Base):
    __tablename__ = "product_knowledge"
    __table_args__ = (
        UniqueConstraint("shop_id", "goods_id", name="uix_product_knowledge_shop_goods"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    goods_id = Column(Integer, nullable=False)
    goods_name = Column(String(255), nullable=False)
    price = Column(String(50), nullable=True)
    price_min = Column(Integer, nullable=True)
    price_max = Column(Integer, nullable=True)
    sold_quantity = Column(Integer, nullable=True)
    thumb_url = Column(String(500), nullable=True)
    specifications = Column(Text, nullable=True)
    extracted_content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_extracted_at = Column(DateTime, default=datetime.now)
    shop = relationship("Shop", backref="product_knowledge")

    def __repr__(self):
        return f"<ProductKnowledge(goods_id='{self.goods_id}', goods_name='{self.goods_name}')>"


class CustomerServiceKnowledge(Base):
    __tablename__ = "customer_service_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    shop = relationship("Shop", backref="customer_service_knowledge")

    def __repr__(self):
        return f"<CustomerServiceKnowledge(title='{self.title}', enabled={self.enabled})>"


class ConversationRecord(Base):
    """Long-lived chat archive, separate from the compressed agent context."""
    __tablename__ = "conversation_records"
    __table_args__ = (
        Index("ix_conversation_records_scope_time", "shop_id", "account_user_id", "customer_uid", "created_at"),
        Index("ix_conversation_records_thread_time", "channel_name", "shop_id", "customer_uid", "created_at"),
        Index("ix_conversation_records_message_type", "message_type"),
        Index("ix_conversation_records_platform_message", "platform_message_id"),
        UniqueConstraint(
            "channel_name", "shop_id", "account_user_id",
            "platform_message_id", "direction",
            name="uix_conversation_record_platform_message",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(255), nullable=False, index=True)
    channel_name = Column(String(50), nullable=False, default="pinduoduo")
    shop_id = Column(String(100), nullable=False)
    shop_name = Column(String(100), nullable=True)
    account_user_id = Column(String(100), nullable=False)
    account_username = Column(String(100), nullable=True)
    customer_uid = Column(String(100), nullable=False)
    customer_nickname = Column(String(255), nullable=True)
    direction = Column(String(16), nullable=False)  # inbound | outbound | event
    sender_type = Column(String(16), nullable=False)  # user | ai | human | system
    event_type = Column(String(32), nullable=False, default="message")
    content = Column(Text, nullable=True)
    platform_message_id = Column(String(255), nullable=True)
    message_type = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="received")  # received|sent|failed
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id, "conversation_id": self.conversation_id,
            "channel_name": self.channel_name, "shop_id": self.shop_id,
            "shop_name": self.shop_name,
            "account_user_id": self.account_user_id, "account_username": self.account_username,
            "customer_uid": self.customer_uid, "customer_nickname": self.customer_nickname,
            "direction": self.direction, "sender_type": self.sender_type,
            "event_type": self.event_type, "content": self.content,
            "platform_message_id": self.platform_message_id,
            "message_type": self.message_type, "status": self.status,
            "metadata": self.metadata_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
