"""Seed (or reset) the synthetic demo dataset.

Run from the repo root:

    python -m services.api.fixtures.seed            # seed if empty
    python -m services.api.fixtures.seed --reset    # wipe and re-seed

The fixtures implement the three agreed acceptance stories:

  F1  Delayed legitimate refund — ORD-3000-RAM: Rs 3,000 payment SUCCEEDED,
      an existing REF-500-001 (Rs 500) is PENDING. Expected app behaviour:
      track the existing refund; never suggest a second payout.

  F2  Repeated request after timeout — ORD-1000-KIRAN: Rs 1,000 payment
      SUCCEEDED, existing REF-1000-002 (Rs 1,000) outcome UNKNOWN.
      Expected: reconcile the existing reference; no replacement payment.

  F3  Ambiguous payment claim — two Rs 799 payments (ORD-799-SALE-A/B) with
      no reference given. Expected: present candidates; stay unmatched until
      the merchant confirms.

Seed data lives in TWO worlds on purpose: the mock provider ledger (``pl_*``,
the provider's truth) and the app tables (the merchant's view). The app view
is constructed only through recorded observations.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from ..app import models
from ..app.config import settings
from ..app.db import SessionLocal, create_all
from ..app.security import hash_password

TENANT_ID = "tnt_demo01"
NOW = datetime.now(timezone.utc)


def minutes_ago(n: int) -> datetime:
    return NOW - timedelta(minutes=n)


# ---------------------------------------------------------------------------
# Provider-side ledger (the mock provider's own truth)
# ---------------------------------------------------------------------------

LEDGER_PAYMENTS = [
    # (provider_txn_id, order_ref, amount_paise, raw status)
    ("MOCK-TXN-3000-001", "ORD-3000-RAM", 300000, "SUCCESS"),
    ("MOCK-TXN-1000-002", "ORD-1000-KIRAN", 100000, "SUCCESS"),
    ("MOCK-TXN-799-A", "ORD-799-SALE-A", 79900, "SUCCESS"),
    ("MOCK-TXN-799-B", "ORD-799-SALE-B", 79900, "SUCCESS"),
    ("MOCK-TXN-450-X", "ORD-450-VINYL", 45000, "SUCCESS"),
    ("MOCK-TXN-1200-Y", "ORD-1200-CABLE", 120000, "PENDING"),
]

LEDGER_REFUNDS = [
    # (refund_ref, provider_txn_id, amount_paise, raw status)
    ("REF-500-001", "MOCK-TXN-3000-001", 50000, "PENDING"),   # F1
    ("REF-1000-002", "MOCK-TXN-1000-002", 100000, "UNKNOWN"), # F2 (timed out)
]

ORDERS = [
    # (order_ref, customer display hint — masked, no real identifiers)
    ("ORD-3000-RAM", "Customer R."),
    ("ORD-1000-KIRAN", "Customer K."),
    ("ORD-799-SALE-A", "Customer P."),
    ("ORD-799-SALE-B", "Customer S."),
    ("ORD-450-VINYL", "Customer D."),
    ("ORD-1200-CABLE", "Customer V."),
]

PAYMENT_STATUS_MAP = {"SUCCESS": "SUCCEEDED", "PENDING": "PENDING", "FAILED": "FAILED"}
REFUND_STATUS_MAP = {"PENDING": "PENDING", "SUCCEEDED": "SUCCEEDED", "FAILED": "FAILED", "UNKNOWN": "UNKNOWN"}


def reset(db) -> None:
    """Delete everything (demo-only convenience)."""
    for table in reversed(models.Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()


def seed(db) -> None:
    # Staged flushes keep foreign-key ordering explicit and deterministic on
    # both SQLite and Postgres (a single mega-flush relies on the ORM's
    # dependency sorter, which is unnecessary risk for a seed script).

    # --- stage 1: tenant, users, memberships, provider settings -----------
    db.add(models.Tenant(
        id=TENANT_ID, name="Maya Mobile Accessories", environment="DEMO_LOCAL",
        provider_account_id="mock_mid_01",
    ))
    db.flush()

    owner = models.User(id="usr_owner", username="owner@demo", display_name="Asha (Owner)",
                        password_hash=hash_password(settings.DEMO_OWNER_PASSWORD))
    staff = models.User(id="usr_staff", username="staff@demo", display_name="Ravi (Staff)",
                        password_hash=hash_password(settings.DEMO_STAFF_PASSWORD))
    researcher = models.User(id="usr_researcher", username="research@demo", display_name="Researcher",
                             password_hash=hash_password(settings.DEMO_RESEARCHER_PASSWORD))
    db.add_all([owner, staff, researcher])
    db.flush()

    db.add_all([
        models.Membership(id="mem_owner", user_id=owner.id, tenant_id=TENANT_ID, role="owner"),
        models.Membership(id="mem_staff", user_id=staff.id, tenant_id=TENANT_ID, role="staff"),
        # Researcher attached to the same demo tenant for prototype simplicity.
        models.Membership(id="mem_researcher", user_id=researcher.id, tenant_id=TENANT_ID, role="researcher"),
    ])
    db.add(models.PlSetting(key="outage", value="false"))
    db.flush()

    # --- stage 2: mock provider ledger (the provider's own truth) ----------
    for txn, order_ref, amount, status in LEDGER_PAYMENTS:
        db.add(models.PlPayment(
            provider_txn_id=txn, provider_account_id="mock_mid_01", order_ref=order_ref,
            amount_paise=amount, currency="INR", status=status,
            created_at=minutes_ago(240),
        ))
    db.flush()
    for ref, txn, amount, status in LEDGER_REFUNDS:
        db.add(models.PlRefund(
            refund_ref=ref, provider_txn_id=txn, amount_paise=amount, currency="INR",
            status=status, created_at=minutes_ago(120), updated_at=minutes_ago(60),
        ))
    db.flush()

    # --- stage 3: app-side records (the merchant's synced view) ------------
    order_ids: dict[str, str] = {}
    payment_ids: dict[str, str] = {}
    amount_map = {x[1]: x[2] for x in LEDGER_PAYMENTS}  # order_ref -> paise
    for order_ref, hint in ORDERS:
        oid = f"ord_{order_ref.lower().replace('-', '_')}"
        order_ids[order_ref] = oid
        db.add(models.Order(
            id=oid, tenant_id=TENANT_ID, environment="DEMO_LOCAL", order_ref=order_ref,
            amount_paise=amount_map[order_ref], currency="INR", customer_hint=hint,
            created_at=minutes_ago(240),
        ))
    db.flush()

    for txn, order_ref, amount, raw_status in LEDGER_PAYMENTS:
        pid = f"pay_{txn.lower().replace('-', '_')}"
        payment_ids[txn] = pid
        db.add(models.Payment(
            id=pid, tenant_id=TENANT_ID, environment="DEMO_LOCAL",
            order_id=order_ids[order_ref], provider_txn_id=txn,
            amount_paise=amount, currency="INR",
            status=PAYMENT_STATUS_MAP[raw_status], verification="VERIFIED",
            last_checked_at=minutes_ago(10), created_at=minutes_ago(230),
        ))
    db.flush()

    for ref, txn, amount, raw_status in LEDGER_REFUNDS:
        rid = f"rfd_{ref.lower().replace('-', '_')}"
        db.add(models.Refund(
            id=rid, tenant_id=TENANT_ID, environment="DEMO_LOCAL",
            payment_id=payment_ids[txn], refund_ref=ref, amount_paise=amount,
            currency="INR", status=REFUND_STATUS_MAP[raw_status], origin="EXTERNAL",
            last_checked_at=minutes_ago(10), created_at=minutes_ago(120),
        ))
    db.flush()

    # --- stage 4: initial-sync observations (provenance for the app view) --
    for txn, order_ref, amount, raw_status in LEDGER_PAYMENTS:
        pid = payment_ids[txn]
        db.add(models.Observation(
            id=f"obs_sync_{pid}", tenant_id=TENANT_ID, environment="DEMO_LOCAL",
            subject_type="payment", subject_key=pid,
            source_kind="provider_mock", verification_status="VERIFIED",
            summary_json=json.dumps({"provider": "mock", "provider_txn_id": txn, "raw_status": raw_status}),
            message=f"Initial sync: provider reports payment {raw_status}.",
            event_time=minutes_ago(230), observed_at=minutes_ago(228),
        ))
    for ref, txn, amount, raw_status in LEDGER_REFUNDS:
        db.add(models.Observation(
            id=f"obs_sync_rfd_{ref.lower().replace('-', '_')}", tenant_id=TENANT_ID,
            environment="DEMO_LOCAL",
            subject_type="refund", subject_key=ref,
            source_kind="provider_mock", verification_status="VERIFIED",
            summary_json=json.dumps({"provider": "mock", "refund_ref": ref, "raw_status": raw_status}),
            message=f"Initial sync: provider reports refund {raw_status} for {ref}.",
            event_time=minutes_ago(120), observed_at=minutes_ago(118),
        ))
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Wipe all data and re-seed.")
    args = parser.parse_args()

    create_all()
    db = SessionLocal()
    try:
        if args.reset:
            print("resetting all tables ...")
            reset(db)
        if db.get(models.Tenant, TENANT_ID) is not None:
            print("already seeded — use --reset to wipe and re-seed")
            return
        seed(db)
        print(f"seeded tenant '{TENANT_ID}' (environment DEMO_LOCAL)")
        print("users: owner@demo / staff@demo / research@demo (passwords from .env defaults)")
        print("fixtures: F1 ORD-3000-RAM (refund PENDING) / F2 ORD-1000-KIRAN (refund UNKNOWN) / "
              "F3 ORD-799-SALE-A+B (ambiguous Rs 799)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
