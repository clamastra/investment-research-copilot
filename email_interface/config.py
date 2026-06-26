"""
email_interface/config.py — Email interface configuration.
All credentials come from environment variables — never hardcoded.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load from the parent project's .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

# Gmail IMAP/SMTP
GMAIL_ADDRESS  = os.getenv("GMAIL_POLLING_ADDRESS", "")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASSWORD", "")

# IMAP settings (Gmail)
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# SMTP settings (Gmail)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# Polling interval (seconds)
POLL_INTERVAL = 300   # 5 minutes

# Paths
PROJECT_ROOT    = Path(__file__).resolve().parent.parent
AGENTIC_ROOT    = PROJECT_ROOT.parent / "agentic-research-assistant"
LOG_FILE        = PROJECT_ROOT / "logs" / "email_requests.jsonl"

# Subject line prefixes (case-insensitive)
PREFIX_RESEARCH = "RESEARCH:"
PREFIX_QUERY    = "QUERY:"

def validate_config() -> list[str]:
    """Returns a list of missing config items (empty = config is valid)."""
    missing = []
    if not GMAIL_ADDRESS:
        missing.append("GMAIL_POLLING_ADDRESS not set in .env")
    if not GMAIL_APP_PASS:
        missing.append("GMAIL_APP_PASSWORD not set in .env")
    if not AGENTIC_ROOT.exists():
        missing.append(f"Agentic assistant not found at {AGENTIC_ROOT}")
    return missing
