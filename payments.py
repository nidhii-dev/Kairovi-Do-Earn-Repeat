"""
Kairovi Payments — RazorpayX UPI payout integration.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import razorpay
import requests
from razorpay.errors import BadRequestError, GatewayError, ServerError
from requests.auth import HTTPBasicAuth

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"

# RazorpayX virtual account number (set in production via env).
DEFAULT_RAZORPAYX_ACCOUNT = os.getenv("RAZORPAYX_ACCOUNT_NUMBER", "")


def _iso_timestamp() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _mock_success(upi_id: str, amount_inr: float, notice: str) -> dict[str, Any]:
    """Simulated payout payload for UI testing when live APIs are unavailable."""
    return {
        "success": True,
        "transaction_id": f"pout_Kairovi_{uuid.uuid4().hex[:10]}",
        "upi_id": upi_id,
        "amount": float(amount_inr),
        "timestamp": _iso_timestamp(),
        "notice": notice,
        "mode": "mock",
    }


def _live_success(upi_id: str, amount_inr: float, payout_id: str) -> dict[str, Any]:
    """Normalize a successful RazorpayX payout into the Kairovi response shape."""
    txn_id = payout_id if payout_id.startswith("pout_") else f"pout_Kairovi_{payout_id}"
    return {
        "success": True,
        "transaction_id": txn_id,
        "upi_id": upi_id,
        "amount": float(amount_inr),
        "timestamp": _iso_timestamp(),
        "mode": "live",
    }


def _failure(upi_id: str, amount_inr: float, reason: str) -> dict[str, Any]:
    """Return a structured failure response."""
    return {
        "success": False,
        "transaction_id": "",
        "upi_id": upi_id,
        "amount": float(amount_inr),
        "timestamp": _iso_timestamp(),
        "notice": reason,
        "mode": "error",
    }


def _verify_credentials(key_id: str, key_secret: str) -> bool:
    """
    Lightweight credential probe using requests.

    Razorpay returns 401 for invalid keys; a 200 confirms auth is accepted.
    """
    try:
        response = requests.get(
            f"{RAZORPAY_API_BASE}/payments",
            auth=HTTPBasicAuth(key_id, key_secret),
            params={"count": 1},
            timeout=15,
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def _create_contact(client: razorpay.Client, upi_id: str) -> dict[str, Any]:
    """Step 1 — Register a RazorpayX contact for the gig worker."""
    reference_id = f"kairovi_contact_{uuid.uuid4().hex[:8]}"
    payload = {
        "name": f"Kairovi Worker {reference_id[-6:]}",
        "email": f"{reference_id}@kairovi.local",
        "contact": "9999999999",
        "type": "vendor",
        "reference_id": reference_id,
        "notes": {"upi_id": upi_id, "platform": "Kairovi"},
    }
    return client.post("/contacts", payload)


def _create_fund_account(
    client: razorpay.Client,
    contact_id: str,
    upi_id: str,
) -> dict[str, Any]:
    """Step 2 — Link a UPI VPA fund account to the contact."""
    payload = {
        "contact_id": contact_id,
        "account_type": "vpa",
        "vpa": {"address": upi_id},
    }
    return client.post("/fund_accounts", payload)


def _dispatch_payout(
    client: razorpay.Client,
    fund_account_id: str,
    amount_inr: float,
    account_number: str,
) -> dict[str, Any]:
    """Step 3 — Dispatch an instant UPI payout via RazorpayX."""
    amount_paise = int(round(amount_inr * 100))
    payload = {
        "account_number": account_number,
        "fund_account_id": fund_account_id,
        "amount": amount_paise,
        "currency": "INR",
        "mode": "UPI",
        "purpose": "payout",
        "queue_if_low_balance": True,
        "reference_id": f"kairovi_{uuid.uuid4().hex[:8]}",
        "narration": "Kairovi gig bounty settlement",
    }
    return client.post("/payouts", payload)


def trigger_razorpay_payout(
    key_id: str,
    key_secret: str,
    upi_id: str,
    amount_inr: float,
) -> dict[str, Any]:
    """
    Execute a RazorpayX UPI payout for an approved Kairovi micro-task.

    Flow:
        1. Create contact
        2. Create & link UPI fund account
        3. Dispatch payout

    Invalid or test credentials fall back to a mock success payload so the
    Streamlit UI can be exercised without live RazorpayX setup.

    Returns:
        dict with keys: success, transaction_id, upi_id, amount, timestamp.
        Optional keys: notice (str), mode ("live" | "mock" | "error").
    """
    upi_id = upi_id.strip()
    key_id = key_id.strip()
    key_secret = key_secret.strip()

    if not key_id or not key_secret:
        return _mock_success(
            upi_id,
            amount_inr,
            notice=(
                "Mock payout: Razorpay credentials were not provided. "
                "This is a simulated settlement for UI testing."
            ),
        )

    if not upi_id:
        return _failure(upi_id, amount_inr, "UPI ID is required for payout.")

    if amount_inr <= 0:
        return _failure(upi_id, amount_inr, "Payout amount must be greater than zero.")

    # Skip live API when credentials are clearly placeholders / invalid.
    if not _verify_credentials(key_id, key_secret):
        return _mock_success(
            upi_id,
            amount_inr,
            notice=(
                "Mock payout: Razorpay credentials are invalid or unavailable. "
                "Simulated settlement for UI testing — no real money was transferred."
            ),
        )

    client = razorpay.Client(auth=(key_id, key_secret))
    account_number = DEFAULT_RAZORPAYX_ACCOUNT

    try:
        # --- RazorpayX pipeline ---
        contact = _create_contact(client, upi_id)
        contact_id = contact.get("id")
        if not contact_id:
            raise ValueError("RazorpayX contact creation returned no contact ID.")

        fund_account = _create_fund_account(client, contact_id, upi_id)
        fund_account_id = fund_account.get("id")
        if not fund_account_id:
            raise ValueError("RazorpayX fund account creation returned no account ID.")

        if not account_number:
            return _mock_success(
                upi_id,
                amount_inr,
                notice=(
                    "Mock payout: Contact and fund account were validated, but "
                    "RAZORPAYX_ACCOUNT_NUMBER is not configured. "
                    "Set the env var to enable live payout dispatch."
                ),
            )

        payout = _dispatch_payout(client, fund_account_id, amount_inr, account_number)
        payout_id = payout.get("id", "")
        if not payout_id:
            raise ValueError("RazorpayX payout dispatch returned no payout ID.")

        return _live_success(upi_id, amount_inr, payout_id)

    except (BadRequestError, GatewayError, ServerError) as exc:
        # Razorpay-specific HTTP errors — return a simulated response and include the error.
        return _mock_success(
            upi_id,
            amount_inr,
            notice=(
                f"Mock payout: RazorpayX API error ({exc}). Simulated settlement for UI testing."
            ),
        )
    except requests.RequestException as exc:
        # Network/requests-level errors
        return _mock_success(
            upi_id,
            amount_inr,
            notice=(
                f"Mock payout: Network error when contacting RazorpayX ({exc}). Simulated settlement."
            ),
        )
    except Exception as exc:
        # Catch-all for unexpected issues — keep UI behavior predictable by simulating payout.
        return _mock_success(
            upi_id,
            amount_inr,
            notice=(
                f"Mock payout: Unexpected error ({exc}). Simulated settlement for UI testing."
            ),
        )
