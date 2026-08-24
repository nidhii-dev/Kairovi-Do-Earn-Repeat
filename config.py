"""
Project configuration loader.

Loads environment variables from a local .env file when available via
python-dotenv and exposes common keys used by the app.
"""

from __future__ import annotations

import os
from typing import Final

try:
	# Optional dependency — load .env when present
	from dotenv import load_dotenv

	load_dotenv()
except Exception:
	# If python-dotenv isn't installed or .env isn't present, silently continue.
	pass

# Exposed configuration values (empty string when not set)
GEMINI_API_KEY: Final[str] = os.getenv("GEMINI_API_KEY", "").strip()
RAZORPAY_KEY_ID: Final[str] = os.getenv("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET: Final[str] = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
RAZORPAYX_ACCOUNT_NUMBER: Final[str] = os.getenv("RAZORPAYX_ACCOUNT_NUMBER", "").strip()


def has_any_credentials() -> bool:
	"""Return True if any configured credential was found in env/.env."""
	return bool(GEMINI_API_KEY or RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET)
