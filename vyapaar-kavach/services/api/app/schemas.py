"""Pydantic request/response contracts for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- auth -----------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: Optional[str] = None  # resolved server-side; defaults to single membership


class MembershipOut(BaseModel):
    tenant_id: str
    tenant_name: str
    role: str


class MeResponse(BaseModel):
    user_id: str
    username: str
    display_name: str
    tenant_id: str
    role: str
    memberships: list[MembershipOut]
    environment: str


# --- payments / refunds ----------------------------------------------------

class RefundOut(BaseModel):
    id: str
    refund_ref: str
    amount_paise: int
    currency: str
    status: str
    origin: str
    last_checked_at: Optional[datetime]

    class Config:
        from_attributes = True


class PaymentSummary(BaseModel):
    id: str
    order_ref: str
    provider_txn_id: str
    amount_paise: int
    currency: str
    status: str
    verification: str
    last_checked_at: Optional[datetime]
    customer_hint: str


class PaymentDetail(PaymentSummary):
    refunds: list[RefundOut]


# --- cases ------------------------------------------------------------------

CLAIM_TYPES = ("REFUND_NOT_RECEIVED", "PAYMENT_NOT_REFLECTED", "OVERPAYMENT", "OTHER")


class CaseCreateRequest(BaseModel):
    claim_type: str
    claimed_amount_paise: Optional[int] = Field(default=None, ge=1)
    reference: str = ""          # order ref or provider txn id, optional
    note: str = ""


class MatchRequest(BaseModel):
    payment_id: str


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ResolveRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=4000)
    case_version: int            # optimistic concurrency guard


class CandidateOut(BaseModel):
    payment_id: str
    order_ref: str
    provider_txn_id: str
    amount_paise: int
    currency: str
    status: str
    created_at: datetime
    reason: str


class CaseOut(BaseModel):
    id: str
    claim_type: str
    claimed_amount_paise: Optional[int]
    reference_text: str
    status: str
    match_status: str
    payment_id: Optional[str]
    created_at: datetime
    created_by: str
    version: int
    resolution_text: Optional[str]
    resolved_by: Optional[str]
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class RecommendationOut(BaseModel):
    case_id: str
    policy_version: str
    action: str
    reason_codes: list[str]
    summary: str
    supporting_observation_ids: list[str]
    missing_facts: list[str]
    provider_last_checked_at: Optional[datetime]
    model_used_for_action: bool
    execution_allowed: bool


class TimelineItem(BaseModel):
    at: datetime
    kind: str          # observation | case_event | note
    source_kind: str
    label: str
    detail: str
    verification_status: Optional[str]


# --- provider events / demo controls ---------------------------------------

class ProviderEventIn(BaseModel):
    subject_type: str              # payment | refund
    subject_ref: str               # provider_txn_id | refund_ref
    status: str                    # raw provider status string
    event_time: datetime
    event_id: Optional[str] = None


class DemoControlRequest(BaseModel):
    scenario: str                  # outage_on | outage_off | refund_f1_succeeds | delayed_pending_f1


class ResearchRunRequest(BaseModel):
    task: str = "elliptic2_smurf_reproduction"
    sample_size: int = Field(default=64, ge=1, le=2000)


class ErrorOut(BaseModel):
    error: str
    code: str
    retryable: bool = False
    detail: Any = None
