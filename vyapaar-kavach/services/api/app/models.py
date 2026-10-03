"""SQLAlchemy data model.

Design notes (implemented, not aspirational — trim per the build plan):

* Every tenant-owned row carries ``tenant_id`` and ``environment``; all queries
  scope through the authenticated membership, never a client-supplied tenant.
* Money is stored as integer **paise** (INR minor units), never floats.
* Payment state and verification state are *separate* dimensions: a payment
  can be SUCCEEDED with a STALE verification when the provider is unreachable.
* The mock provider keeps its own ledger tables (``pl_*``) — the app's view of
  the world is built only from *observations*, mirroring a real integration.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Identity & tenancy
# --------------------------------------------------------------------------

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    environment: Mapped[str] = mapped_column(String(32), default="DEMO_LOCAL")
    provider_account_id: Mapped[str] = mapped_column(String(64), default="mock_mid_01")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200))

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Membership(Base):
    """Roles: owner | staff | researcher. Role is resolved server-side only."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_member"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    role: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship()


class Session(Base):
    """Opaque expiring demo session. The raw token is the lookup key."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # the token itself
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
    tenant: Mapped[Tenant] = relationship()


# --------------------------------------------------------------------------
# Merchant operational records
# --------------------------------------------------------------------------

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "environment", "order_ref", name="uq_order_ref"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    environment: Mapped[str] = mapped_column(String(32))
    order_ref: Mapped[str] = mapped_column(String(64))
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    customer_hint: Mapped[str] = mapped_column(String(120), default="")  # masked label only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    payments: Mapped[list["Payment"]] = relationship(back_populates="order")


class Payment(Base):
    """App-side projection of a payment. Truth comes from observations."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    environment: Mapped[str] = mapped_column(String(32))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    provider_txn_id: Mapped[str] = mapped_column(String(64), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")

    # UNKNOWN | PENDING | SUCCEEDED | FAILED | NO_RECORD
    status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    # UNVERIFIED | VERIFIED | STALE | CONFLICTED
    verification: Mapped[str] = mapped_column(String(16), default="UNVERIFIED")
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="payments")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="payment")


class Refund(Base):
    """App-side record of a refund known to us (local or external origin).

    There is deliberately NO destination/account field: supported refunds
    always follow the original payment's source route.
    """

    __tablename__ = "refunds"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    environment: Mapped[str] = mapped_column(String(32))
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    refund_ref: Mapped[str] = mapped_column(String(64), index=True)  # immutable reference
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    # PENDING | SUCCEEDED | FAILED | UNKNOWN
    status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    origin: Mapped[str] = mapped_column(String(16), default="EXTERNAL")  # EXTERNAL|LOCAL
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    payment: Mapped[Payment] = relationship(back_populates="refunds")


class ProviderEvent(Base):
    """Raw inbound provider notifications (mock). Fingerprint-deduplicated."""

    __tablename__ = "provider_events"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_event_fingerprint"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="mock")
    fingerprint: Mapped[str] = mapped_column(String(64))  # sha256 of canonical payload
    subject_type: Mapped[str] = mapped_column(String(16))  # payment | refund
    subject_ref: Mapped[str] = mapped_column(String(64))   # provider_txn_id | refund_ref
    raw_json: Mapped[str] = mapped_column(Text)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # ACCEPTED | DUPLICATE | REJECTED
    processing: Mapped[str] = mapped_column(String(16), default="ACCEPTED")


class Observation(Base):
    """One verified (or rejected) fact about a payment/refund, with provenance.

    source_kind: provider_mock | merchant_statement | system_derived | model
    verification_status: VERIFIED | UNVERIFIED | STALE | CONFLICTED
    """

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    environment: Mapped[str] = mapped_column(String(32))
    subject_type: Mapped[str] = mapped_column(String(16))  # payment | refund | case
    subject_key: Mapped[str] = mapped_column(String(64), index=True)  # payment id or refund_ref
    source_kind: Mapped[str] = mapped_column(String(24))
    verification_status: Mapped[str] = mapped_column(String(16))
    summary_json: Mapped[str] = mapped_column(Text)  # compact machine payload
    message: Mapped[str] = mapped_column(Text, default="")  # human summary
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    environment: Mapped[str] = mapped_column(String(32))
    # claim_type: REFUND_NOT_RECEIVED | PAYMENT_NOT_REFLECTED | OVERPAYMENT | OTHER
    claim_type: Mapped[str] = mapped_column(String(32))
    claimed_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_text: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN|RESOLVED
    match_status: Mapped[str] = mapped_column(String(16), default="UNMATCHED")  # UNMATCHED|MATCHED
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolution_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic edit guard

    payment: Mapped[Payment | None] = relationship()
    notes: Mapped[list["CaseNote"]] = relationship(back_populates="case")


class CaseNote(Base):
    __tablename__ = "case_notes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    author_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="notes")
    author: Mapped[User] = relationship()


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    storage_path: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """Lightweight job log. Demo jobs execute in-process but are recorded."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="COMPLETED")  # COMPLETED|FAILED
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task: Mapped[str] = mapped_column(String(64))
    data_mode: Mapped[str] = mapped_column(String(16))  # ORIGINAL_DOMAIN_RESEARCH | SYNTHETIC
    model_version: Mapped[str] = mapped_column(String(64))
    checkpoint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    abstention_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    runtime_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# Mock provider ledger — the *provider's* truth, separate from app records.
# Reconciliation tests rely on this separation.
# --------------------------------------------------------------------------

class PlPayment(Base):
    __tablename__ = "pl_payments"

    provider_txn_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_account_id: Mapped[str] = mapped_column(String(64), index=True)  # maps to tenant
    order_ref: Mapped[str] = mapped_column(String(64))
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(16))  # SUCCESS|PENDING|FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlRefund(Base):
    __tablename__ = "pl_refunds"

    refund_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_txn_id: Mapped[str] = mapped_column(ForeignKey("pl_payments.provider_txn_id"))
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(16))  # PENDING|SUCCEEDED|FAILED|UNKNOWN
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlSetting(Base):
    """Provider-side toggles used by demo controls (e.g. simulated outage)."""

    __tablename__ = "pl_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
