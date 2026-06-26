"""
email_interface/poll.py — Gmail polling and dispatch daemon.
-------------------------------------------------------------
Checks a dedicated Gmail inbox every 5 minutes, processes requests,
and emails back results.

Run persistently in a tmux session:
    tmux new -s email-poll
    cd investment-research-copilot
    venv/Scripts/python email_interface/poll.py

Stop with Ctrl+C. Restart by re-running the command.

Subject line conventions:
    RESEARCH: AAPL           -> Full agentic research brief via agentic-research-assistant
    QUERY: What are risks?   -> CapitalContext RAG query with citations

IMPORTANT: Send requests from a personal Gmail account.
Do NOT send from a work email -- your firm's DLP (data loss prevention)
system may flag, quarantine, or log emails containing financial tickers
or investment-related terms. This could create compliance problems even
for a personal project. Use a personal phone or personal Gmail only.
"""

import imaplib
import smtplib
import email
import json
import time
import traceback
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header
from pathlib import Path

from email_interface.config import (
    GMAIL_ADDRESS, GMAIL_APP_PASS,
    IMAP_HOST, IMAP_PORT,
    SMTP_HOST, SMTP_PORT,
    POLL_INTERVAL, LOG_FILE,
    PREFIX_RESEARCH, PREFIX_QUERY,
    validate_config,
)
from email_interface.router import parse_subject, route
from email_interface.formatter import (
    build_confirmation_email,
    build_response_email,
    build_error_email,
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def _log(event: dict) -> None:
    """Appends one event to the JSONL audit log."""
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


def _print(msg: str) -> None:
    print(f"[{_ts()}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# IMAP helpers
# ---------------------------------------------------------------------------

def _connect_imap() -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    imap.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
    return imap


def _decode_header_value(value: str) -> str:
    """Decodes encoded email headers (e.g. UTF-8 or base64 encoded subjects)."""
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _get_body(msg) -> str:
    """Extracts plain-text body from an email.Message object."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and part.get_content_disposition() != "attachment":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="replace")
    return ""


def _fetch_unread(imap: imaplib.IMAP4_SSL) -> list[tuple[bytes, str, str, str]]:
    """
    Fetches all unread messages in INBOX.
    Returns list of (uid_bytes, sender, subject, body).
    """
    imap.select("INBOX")
    _, data = imap.search(None, "UNSEEN")
    uids = data[0].split()

    messages = []
    for uid in uids:
        _, raw = imap.fetch(uid, "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])
        sender  = _decode_header_value(msg.get("From", ""))
        subject = _decode_header_value(msg.get("Subject", ""))
        body    = _get_body(msg)
        messages.append((uid, sender, subject, body))

    return messages


def _mark_read(imap: imaplib.IMAP4_SSL, uid: bytes) -> None:
    imap.store(uid, "+FLAGS", "\\Seen")


# ---------------------------------------------------------------------------
# SMTP helpers
# ---------------------------------------------------------------------------

def _send_email(to: str, subject: str, html_body: str) -> None:
    """Sends an HTML email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = to
    msg["Subject"] = subject

    # Plain-text fallback (strip tags roughly)
    import re
    plain = re.sub(r"<[^>]+>", "", html_body)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        smtp.sendmail(GMAIL_ADDRESS, to, msg.as_string())


# ---------------------------------------------------------------------------
# Request processing
# ---------------------------------------------------------------------------

def _extract_sender_address(from_header: str) -> str:
    """Extracts bare email address from 'Name <email@example.com>' format."""
    import re
    match = re.search(r"<(.+?)>", from_header)
    return match.group(1) if match else from_header.strip()


def process_message(uid: bytes, sender: str, subject: str, body: str,
                    imap: imaplib.IMAP4_SSL) -> None:
    """Processes a single unread email: confirm → route → respond → mark read."""
    reply_to = _extract_sender_address(sender)
    _print(f"Processing: '{subject}' from {reply_to}")

    # Parse subject
    mode, query = parse_subject(subject)

    if mode is None:
        _print(f"  Unrecognised subject format, sending usage hint.")
        try:
            _send_email(
                to=reply_to,
                subject=f"Re: {subject} [unrecognised format]",
                html_body=build_error_email(
                    subject,
                    "Subject line not recognised. Use RESEARCH: [ticker] or QUERY: [question]."
                ),
            )
        except Exception as e:
            _print(f"  Failed to send error reply: {e}")
        _mark_read(imap, uid)
        _log({"event": "unrecognised_subject", "from": reply_to, "subject": subject})
        return

    # Send immediate confirmation
    try:
        _send_email(
            to=reply_to,
            subject=f"Re: {subject} [received]",
            html_body=build_confirmation_email(mode, query),
        )
        _print(f"  Confirmation sent to {reply_to}")
    except Exception as e:
        _print(f"  Warning: confirmation send failed: {e}")

    _log({"event": "request_received", "mode": mode, "query": query, "from": reply_to})

    # Route to backend
    _print(f"  Running {mode} for: {query}")
    t0 = time.time()
    result = route(mode, query)
    elapsed = round(time.time() - t0, 1)
    result.setdefault("elapsed", elapsed)

    _log({
        "event":   "request_completed",
        "mode":    mode,
        "query":   query,
        "from":    reply_to,
        "elapsed": elapsed,
        "cost":    result.get("cost", 0),
        "error":   result.get("error"),
    })

    # Send response
    try:
        _send_email(
            to=reply_to,
            subject=f"Re: {subject} [result]",
            html_body=build_response_email(result),
        )
        _print(f"  Response sent ({elapsed}s, ${result.get('cost', 0):.4f})")
    except Exception as e:
        _print(f"  ERROR: failed to send response: {e}")
        _log({"event": "send_failed", "error": str(e), "query": query})

    # Mark email as read so it isn't re-processed
    _mark_read(imap, uid)


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------

def run_poll_loop() -> None:
    """Runs the polling loop indefinitely. Ctrl+C to stop."""
    _print("=" * 55)
    _print("CapitalContext Email Interface - Starting")
    _print(f"Polling: {GMAIL_ADDRESS}")
    _print(f"Interval: {POLL_INTERVAL}s ({POLL_INTERVAL // 60} min)")
    _print(f"Log: {LOG_FILE}")
    _print("=" * 55)

    errors = validate_config()
    if errors:
        _print("ERROR: Configuration problems:")
        for e in errors:
            _print(f"  - {e}")
        _print("Fix .env and retry. Exiting.")
        return

    _log({"event": "poller_started", "address": GMAIL_ADDRESS})

    while True:
        try:
            _print("Checking inbox...")
            imap = _connect_imap()
            messages = _fetch_unread(imap)

            if not messages:
                _print(f"  No new messages. Next check in {POLL_INTERVAL}s.")
            else:
                _print(f"  {len(messages)} unread message(s) found.")
                for uid, sender, subject, body in messages:
                    try:
                        process_message(uid, sender, subject, body, imap)
                    except Exception:
                        err = traceback.format_exc()
                        _print(f"  Unhandled error processing message: {err}")
                        _log({"event": "processing_exception", "error": err,
                              "subject": subject, "from": sender})

            imap.logout()

        except imaplib.IMAP4.error as e:
            _print(f"IMAP error: {e}. Will retry next cycle.")
            _log({"event": "imap_error", "error": str(e)})
        except OSError as e:
            _print(f"Network error: {e}. Will retry next cycle.")
            _log({"event": "network_error", "error": str(e)})
        except KeyboardInterrupt:
            _print("Stopped by user (Ctrl+C).")
            _log({"event": "poller_stopped"})
            break

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_poll_loop()
