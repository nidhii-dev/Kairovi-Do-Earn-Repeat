"""
Kairovi — Autonomous Micro-Task Platform
Streamlit single-page app for gig workers and business agents.
"""

from __future__ import annotations

import re
from typing import TypedDict
from io import BytesIO
from PIL import Image, UnidentifiedImageError

import streamlit as st

from config import GEMINI_API_KEY, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from ai_engine import verify_proof_with_gemini, get_image_hash
from payments import trigger_razorpay_payout

# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------


class Task(TypedDict):
    """A micro-bounty posted by a business agent."""

    title: str
    location: str
    bounty: float
    prompt: str


class VerificationResult(TypedDict):
    """Structured output from Gemini vision verification."""

    passed: bool
    reason: str


class PayoutResult(TypedDict, total=False):
    """Razorpay UPI payout response from payments.py."""

    success: bool
    transaction_id: str
    upi_id: str
    amount: float
    timestamp: str
    notice: str
    mode: str


# ---------------------------------------------------------------------------
# Constants & defaults
# ---------------------------------------------------------------------------

DEFAULT_TASK: Task = {
    "title": "Verify Menu Prices at Joe's Diner",
    "location": "Indiranagar, Bengaluru",
    "bounty": 150.0,
    "prompt": (
        "Is this a clear photo of a restaurant menu, storefront sign, or receipt "
        "that explicitly shows the restaurant name ('Joe\'s Diner' or 'Joe\'s') AND displays visible menu items with prices?"
    ),
}

UPI_PATTERN = re.compile(r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$")


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------


def init_session_state() -> None:
    """Bootstrap persistent keys used across reruns."""
    if "tasks" not in st.session_state:
        st.session_state.tasks: list[Task] = [DEFAULT_TASK.copy()]

    # Load any configured defaults from config.py (.env via python-dotenv)
    if "gemini_api_key" not in st.session_state:
        st.session_state.gemini_api_key = GEMINI_API_KEY or ""

    if "razorpay_key_id" not in st.session_state:
        st.session_state.razorpay_key_id = RAZORPAY_KEY_ID or ""

    if "razorpay_key_secret" not in st.session_state:
        st.session_state.razorpay_key_secret = RAZORPAY_KEY_SECRET or ""

    if "last_verification" not in st.session_state:
        st.session_state.last_verification: VerificationResult | None = None

    if "last_payout" not in st.session_state:
        st.session_state.last_payout: PayoutResult | None = None

    if "submitted_hashes" not in st.session_state:
        st.session_state.submitted_hashes: set[str] = set()


def is_valid_upi(upi_id: str) -> bool:
    """Basic UPI ID format validation."""
    return bool(UPI_PATTERN.match(upi_id.strip()))


def task_label(task: Task) -> str:
    """Human-readable label for dropdowns."""
    return f"{task['title']} — ₹{task['bounty']:.0f} ({task['location']})"


# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------


def render_header() -> None:
    """Minimalist top header."""
    st.markdown(
        """
        <div style="padding-bottom: 0.5rem; border-bottom: 1px solid #e6e6e6; margin-bottom: 1.5rem;">
            <h1 style="margin: 0; font-size: 2rem; font-weight: 700;">⚡ Kairovi</h1>
            <p style="margin: 0.25rem 0 0 0; color: #666; font-size: 1rem;">
                Autonomous Micro-Task Agent &amp; Instant UPI Settlements
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    """System credentials — persisted via session state keys."""
    with st.sidebar:
        st.markdown("### 🔐 System Credentials")
        st.caption("Keys persist for this browser session.")

        st.text_input(
            "Gemini API Key",
            type="password",
            placeholder="AIza…",
            key="gemini_api_key",
            value=st.session_state.get("gemini_api_key", ""),
            help="Required for AI proof verification.",
        )
        st.text_input(
            "Razorpay Key ID",
            placeholder="rzp_live_…",
            key="razorpay_key_id",
            value=st.session_state.get("razorpay_key_id", ""),
        )
        st.text_input(
            "Razorpay Key Secret",
            type="password",
            placeholder="••••••••",
            key="razorpay_key_secret",
            value=st.session_state.get("razorpay_key_secret", ""),
        )

        st.divider()
        st.markdown("**Active bounties**")
        st.metric("Open tasks", len(st.session_state.tasks))


def render_bounty_cards(tasks: list[Task]) -> None:
    """Display active bounties as compact status cards."""
    if not tasks:
        st.info("No active bounties. Business agents can post new tasks in the portal tab.")
        return

    cols = st.columns(min(len(tasks), 3))
    for idx, task in enumerate(tasks):
        with cols[idx % len(cols)]:
            with st.container(border=True):
                st.markdown(f"**{task['title']}**")
                st.caption(f"📍 {task['location']}")
                st.markdown(f"**₹{task['bounty']:.0f}** bounty")


def render_gig_worker_tab() -> None:
    """Tab 1 — Gig worker submission flow."""
    tasks: list[Task] = st.session_state.tasks

    st.subheader("📱 Gig Worker App")
    st.caption("Pick a bounty, upload proof, and get paid instantly on approval.")

    render_bounty_cards(tasks)

    if not tasks:
        return

    st.divider()

    # Task selection
    labels = [task_label(t) for t in tasks]
    selected_label = st.radio(
        "Select active task",
        options=labels,
        index=0,
        horizontal=True,
    )
    selected_task = tasks[labels.index(selected_label)]

    with st.container(border=True):
        col_info, col_form = st.columns([1, 1])

        with col_info:
            st.markdown("#### Task details")
            st.markdown(f"**Title:** {selected_task['title']}")
            st.markdown(f"**Location:** {selected_task['location']}")
            st.markdown(f"**Bounty:** ₹{selected_task['bounty']:.0f}")
            st.markdown("**AI verification criteria**")
            st.info(selected_task["prompt"])

        with col_form:
            st.markdown("#### Submit proof")
            upi_id = st.text_input(
                "Worker UPI ID",
                placeholder="user@upi",
                key="worker_upi_id",
            )
            # Require a live camera capture to harden against web-downloaded images
            uploaded = st.camera_input("📷 Take Live Photo Proof", key="live_camera")

            if uploaded is not None:
                st.image(uploaded, caption="Live preview", use_container_width=True)

            submitted = st.button(
                "🚀 Submit to Kairovi AI",
                type="primary",
                use_container_width=True,
            )

    if not submitted:
        return

    # --- Validation ---
    gemini_key = st.session_state.gemini_api_key.strip()
    if not gemini_key:
        st.error("Gemini API Key is required. Add it in the sidebar under System Credentials.")
        return

    if not upi_id.strip():
        st.error("Please enter your UPI ID (e.g., user@upi).")
        return

    if not is_valid_upi(upi_id):
        st.error("Invalid UPI ID format. Use the pattern: name@bank (e.g., user@upi).")
        return

    if uploaded is None:
        st.error("Please take a live photo proof using your camera.")
        return

    # Basic Pillow-based metadata check to help ensure the photo is a live capture
    image_bytes = uploaded.getvalue()
    # Image hash duplication prevention — check before calling Gemini
    try:
        image_hash = get_image_hash(image_bytes)
    except Exception:
        st.error("Failed to compute image hash. Please retake the photo.")
        return

    if image_hash in st.session_state.submitted_hashes:
        st.error("Duplicate photo detected. Please capture a new live photo.")
        return
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img.verify()
        # Re-open to read metadata (verify() may close the file)
        with Image.open(BytesIO(image_bytes)) as img:
            exif = None
            try:
                exif = img.getexif()
            except Exception:
                exif = None

            info = img.info or {}

            # Require either EXIF data or a non-empty info dict indicating camera capture
            if (not exif or len(exif) == 0) and (not info):
                st.error(
                    "Photo appears to be missing camera metadata (EXIF). "
                    "Please use your device camera to take a live photo proof."
                )
                return
    except UnidentifiedImageError:
        st.error("Uploaded image could not be decoded. Please retake the photo.")
        return
    except Exception as exc:
        st.error(f"Image validation failed: {exc}")
        return

    # image_bytes already validated above

    # --- Verification & payout ---
    # Append anti-fraud parameters to the task prompt automatically
    combined_prompt = (
        f"Verify the following criteria: {selected_task['prompt']}. "
        "Ensure the photo is a real-world, physical setting captured live on site."
    )

    with st.spinner("Kairovi AI is verifying your proof with Gemini Flash…"):
        result = verify_proof_with_gemini(
            api_key=gemini_key,
            image_bytes=image_bytes,
            prompt_criteria=combined_prompt,
        )

    st.session_state.last_verification = result

    # Record image hash to prevent re-use if verification completed
    try:
        st.session_state.submitted_hashes.add(image_hash)
    except Exception:
        # Non-fatal — continue if we can't persist the hash
        pass

    # Audit result box
    with st.container(border=True):
        st.markdown("#### 🔍 Audit Result")
        if result["passed"]:
            st.success(f"**PASSED** — {result['reason']}")
        else:
            st.warning(f"**FAILED** — {result['reason']}")

    if not result["passed"]:
        st.info("Payout was not triggered because verification did not pass.")
        return

    # Trigger payout on pass
    rzp_id = st.session_state.razorpay_key_id.strip()
    rzp_secret = st.session_state.razorpay_key_secret.strip()

    if not rzp_id or not rzp_secret:
        st.warning(
            "Proof passed, but Razorpay credentials are missing in the sidebar. "
            "Payout simulation skipped."
        )
        return

    with st.spinner("Triggering instant UPI settlement via Razorpay…"):
        payout = trigger_razorpay_payout(
            key_id=rzp_id,
            key_secret=rzp_secret,
            upi_id=upi_id.strip(),
            amount_inr=selected_task["bounty"],
        )

    st.session_state.last_payout = payout

    with st.container(border=True):
        st.markdown("#### 💸 Payout Confirmation")
        if payout.get("success"):
            st.success(
                f"₹{payout['amount']:.0f} sent to **{payout['upi_id']}** "
                f"(Txn: `{payout['transaction_id']}`)"
            )
            if payout.get("notice"):
                st.info(payout["notice"])
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("Mode", payout.get("mode", "live").upper())
            pc2.metric("Transaction ID", payout["transaction_id"])
            pc3.metric("Amount (INR)", f"₹{payout['amount']:.0f}")
            st.caption(f"Processed at {payout['timestamp']} UTC")
        else:
            st.error(payout.get("notice", "Payout could not be completed."))


def render_business_agent_tab() -> None:
    """Tab 2 — Post new micro-bounties."""
    st.subheader("🏢 Business Agent Portal")
    st.caption("Delegate real-world verification tasks to the Kairovi gig network.")

    with st.container(border=True):
        with st.form("post_bounty_form", clear_on_submit=True):
            st.markdown("#### Post a new micro-bounty")

            title = st.text_input(
                "Task Title",
                placeholder="Verify storefront signage at …",
            )
            location = st.text_input(
                "Location",
                placeholder="Koramangala, Bengaluru",
            )
            bounty = st.number_input(
                "Bounty Amount (INR)",
                min_value=1.0,
                max_value=100_000.0,
                value=150.0,
                step=50.0,
            )
            prompt = st.text_area(
                "AI Verification Criteria (Gemini Prompt)",
                placeholder=(
                    "e.g., Verify storefront sign displaying 'Joe's Diner' and clear prices on the menu board."
                ),
                height=120,
            )

            posted = st.form_submit_button(
                "Post & Fund Bounty",
                type="primary",
                use_container_width=True,
            )

    if not posted:
        return

    # Validate form fields
    errors: list[str] = []
    if not title.strip():
        errors.append("Task Title is required.")
    if not location.strip():
        errors.append("Location is required.")
    if bounty <= 0:
        errors.append("Bounty Amount must be greater than zero.")
    if not prompt.strip():
        errors.append("AI Verification Criteria is required.")

    if errors:
        for msg in errors:
            st.error(msg)
        return

    new_task: Task = {
        "title": title.strip(),
        "location": location.strip(),
        "bounty": float(bounty),
        "prompt": prompt.strip(),
    }
    st.session_state.tasks.append(new_task)

    # Show the requested success banner message when a task is published.
    st.success("Task published and live for gig workers!")
    st.toast(f"Bounty {new_task['title']} posted for ₹{new_task['bounty']:.0f} at {new_task['location']}", icon="✅")
    # Ensure the newly posted task is immediately available in the Gig Worker tab
    try:
        st.experimental_rerun()
    except Exception:
        # If rerun isn't possible in the current environment, continue silently.
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Kairovi",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_session_state()
    render_sidebar()
    render_header()

    tab_gig, tab_business = st.tabs(["📱 Gig Worker App", "🏢 Business Agent Portal"])

    with tab_gig:
        render_gig_worker_tab()

    with tab_business:
        render_business_agent_tab()


if __name__ == "__main__":
    main()
