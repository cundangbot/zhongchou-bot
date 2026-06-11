from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    String, Integer, BigInteger, DateTime, Text, Boolean, UniqueConstraint,
    Numeric, Index, text as sql_text
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db.registry import Base

MONEY = Numeric(14, 2)


class CrowdfundProject(Base):
    __tablename__ = 'crowdfund_projects'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    creator_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    blogger: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    description_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    description_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    description_items: Mapped[str | None] = mapped_column(Text, nullable=True)
    buy_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_price: Mapped[Decimal] = mapped_column(MONEY)
    seat_price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal('30.00'))
    required_seats: Mapped[int] = mapped_column(Integer)
    paid_seats: Mapped[int] = mapped_column(Integer, default=0)
    extra_fund_count: Mapped[int] = mapped_column(Integer, default=0)
    extra_withdrawn_count: Mapped[int] = mapped_column(Integer, default=0)
    creator_withdraw_times: Mapped[int] = mapped_column(Integer, default=0)
    purchase_mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(48), default='pending_review', index=True)
    status_version: Mapped[int] = mapped_column(Integer, default=1)
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resource_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    full_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProjectStateHistory(Base):
    __tablename__ = 'project_state_history'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    from_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    to_status: Mapped[str] = mapped_column(String(48), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PaymentOrder(Base):
    __tablename__ = 'payment_orders'
    __table_args__ = (
        UniqueConstraint('faka_system_no', name='uq_faka_system_no'),
        UniqueConstraint('faka_pay_no', name='uq_faka_pay_no'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    wish_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    expected_amount: Mapped[Decimal] = mapped_column(MONEY)
    order_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default='pending', index=True)
    payment_source: Mapped[str] = mapped_column(String(24), default='real')  # real/seed/test/manual
    faka_system_no: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    paid_channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paid_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    faka_pay_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    faka_buyer_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    faka_order_bot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    effects_applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    expiry_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ResourceAccess(Base):
    __tablename__ = 'resource_access'
    __table_args__ = (UniqueConstraint('user_id', 'project_id', name='uq_user_project_access'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    source_order_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupportBridgeMessage(Base):
    __tablename__ = 'support_bridge_messages'
    __table_args__ = (
        UniqueConstraint('admin_id', 'admin_message_id', name='uq_support_bridge_admin_message'),
        Index('ix_support_bridge_ticket_created', 'ticket_id', 'created_at'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    admin_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    direction: Mapped[str] = mapped_column(String(16), default='user_to_admin')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)



class SupportAdminSession(Base):
    __tablename__ = 'support_admin_sessions'
    __table_args__ = (
        UniqueConstraint('admin_id', name='uq_support_admin_session_admin'),
        Index('ix_support_admin_sessions_ticket', 'ticket_id'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    ticket_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ResourceClaimProgress(Base):
    __tablename__ = 'resource_claim_progress'
    __table_args__ = (UniqueConstraint('user_id', 'project_id', 'resource_kind', name='uq_claim_progress'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    resource_kind: Mapped[str] = mapped_column(String(32), default='all')
    next_page: Mapped[int] = mapped_column(Integer, default=0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    delivered_items: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ResourceClaimLog(Base):
    __tablename__ = 'resource_claim_logs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    resource_kind: Mapped[str] = mapped_column(String(32), default='all')
    page: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProfitWithdrawal(Base):
    __tablename__ = 'profit_withdrawals'
    __table_args__ = (
        Index(
            'uq_active_reimbursement_per_project', 'project_id', unique=True,
            postgresql_where=sql_text("payout_type = 'reimbursement' AND status IN ('pending_info','pending_admin','paid')"),
            sqlite_where=sql_text("payout_type = 'reimbursement' AND status IN ('pending_info','pending_admin','paid')"),
        ),
        Index(
            'uq_active_profit_request_per_project', 'project_id', unique=True,
            postgresql_where=sql_text("payout_type = 'profit' AND status IN ('pending_info','pending_admin')"),
            sqlite_where=sql_text("payout_type = 'profit' AND status IN ('pending_info','pending_admin')"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    payout_type: Mapped[str] = mapped_column(String(32), default='profit')
    extra_count: Mapped[int] = mapped_column(Integer, default=10)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY)
    creator_amount: Mapped[Decimal] = mapped_column(MONEY)
    platform_amount: Mapped[Decimal] = mapped_column(MONEY)
    payout_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='pending_info', index=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RefundRecord(Base):
    __tablename__ = 'refund_records'
    __table_args__ = (UniqueConstraint('order_id', name='uq_refund_order'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal('0.00'))
    status: Mapped[str] = mapped_column(String(32), default='pending_info', index=True)
    payout_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FinancialLedger(Base):
    __tablename__ = 'financial_ledger'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(12))  # income/expense/neutral
    category: Mapped[str] = mapped_column(String(48), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal('0.00'))
    payment_source: Mapped[str] = mapped_column(String(24), default='real')
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    refund_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payout_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class OperationIdempotency(Base):
    __tablename__ = 'operation_idempotency'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    operation_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default='processing')
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SystemEvent(Base):
    __tablename__ = 'system_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default='warning', index=True)
    message: Mapped[str] = mapped_column(Text)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SystemMetric(Base):
    __tablename__ = 'system_metrics'
    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FundLedger(Base):
    """旧版兼容表。新资金流水统一使用 FinancialLedger。"""
    __tablename__ = 'fund_ledger'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    direction: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(128))
    ref_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Wish(Base):
    __tablename__ = 'wishes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    creator_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    blogger: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    description_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    description_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    estimated_price: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(32), default='pending_vote')
    vote_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Vote(Base):
    __tablename__ = 'votes'
    __table_args__ = (UniqueConstraint('user_id', 'round_key', name='uq_user_round_vote'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    wish_id: Mapped[int] = mapped_column(Integer, index=True)
    round_key: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RiskLog(Base):
    __tablename__ = 'risk_logs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_no: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class UserBlacklist(Base):
    __tablename__ = 'user_blacklist'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ContactTicket(Base):
    __tablename__ = 'contact_tickets'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='open', index=True)
    user_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_page: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    refund_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
