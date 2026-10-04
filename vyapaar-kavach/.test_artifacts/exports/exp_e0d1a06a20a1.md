# Vyapaar Kavach — case evidence summary

> Synthetic demo data · mock payment provider · no real funds involved.

Generated: 2026-10-03T20:36:58.406503+00:00 · Environment: DEMO_LOCAL · Schema: case-export.v1

## Case
- ID: case_e98465b740c7
- Claim: REFUND_NOT_RECEIVED · Amount claimed: Rs 500.00 · Status: OPEN / MATCHED
- Customer reference given: ORD-3000-RAM
- Created: 2026-10-03T20:36:58.390027

## Payment
- Order: ORD-3000-RAM · Provider txn: MOCK-TXN-3000-001
- Amount: Rs 3,000.00 · Status: SUCCEEDED · Verification: VERIFIED
- Last provider check: 2026-10-03T20:26:42.498046

## Refunds
- REF-500-001: Rs 500.00 — PENDING (origin EXTERNAL, checked 2026-10-03T20:26:42.498046)

## Evidence timeline (observations)
- [2026-10-03T16:48:42.498046] (provider_mock, VERIFIED) Initial sync: provider reports payment SUCCESS.
- [2026-10-03T18:38:42.498046] (provider_mock, VERIFIED) Initial sync: provider reports refund PENDING for REF-500-001.

## Merchant notes
- [2026-10-03T20:36:58.391027] Asha (Owner): Refund not received
- [2026-10-03T20:36:58.397034] Asha (Owner): Customer called again.

## Recommendation (deterministic policy)
- Action: CHECK_EXISTING_REFUND · Policy: exceptions.v1
- Reasons: REFUND_ALREADY_PENDING
- Summary: A refund already exists for this payment and is pending. Track it before doing anything else.
- Missing facts: —
- Model used for action: False

## Limitations
- Synthetic/demo data with a mock payment provider; no real funds are involved.
- This packet organises available evidence; it is not a legal determination, does not prove innocence or fault, and does not guarantee payment finality.
- A file hash detects later modification of this export only.
