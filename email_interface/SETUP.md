# Email Interface — Setup Instructions

This gives you remote access to both CapitalContext and the Agentic Research
Assistant from any device — including work computers where nothing is installed.
You send an email; your laptop processes it and emails back a research brief.

---

## IMPORTANT: Do NOT use your work email

Your firm's DLP (data loss prevention) system may scan outbound email for
financial keywords — tickers, fund names, investment terms. Even from a personal
project perspective, sending `RESEARCH: AAPL` through your work inbox could be
logged, flagged, or blocked by compliance systems. Use a personal Gmail account
or your personal phone's email client. Never put your work email in the loop.

---

## Step 1: Create a dedicated Gmail account

1. Go to [accounts.google.com](https://accounts.google.com) and create a new Google account.
   Suggested name pattern: `yourname.capitalcontext@gmail.com`
2. This is the account the polling script will **log into** to check for incoming requests.
3. It is also the account that **sends replies** back to you.
4. On your phone/personal computer, you send requests **to** this address.

---

## Step 2: Enable 2-Factor Authentication (required for App Passwords)

1. Sign into the new Gmail account.
2. Go to: **Google Account → Security → 2-Step Verification**
3. Complete the 2FA setup (phone prompt or authenticator app).
4. This is required before Gmail will generate an App Password.

---

## Step 3: Generate a Gmail App Password

App Passwords let a script log in without your real Gmail password.

1. Sign into the new Gmail account.
2. Go to: **Google Account → Security → 2-Step Verification → App Passwords**
   (Direct URL: `myaccount.google.com/apppasswords`)
3. Under "Select app", choose **Mail**.
4. Under "Select device", choose **Windows Computer** (or Other).
5. Click **Generate**.
6. Copy the 16-character password shown. **Save it now — you won't see it again.**

---

## Step 4: Add credentials to .env

Open `investment-research-copilot/.env` and add:

```
GMAIL_POLLING_ADDRESS=yourname.capitalcontext@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

Replace the address and password with your actual values.
The App Password may have spaces — keep them, they're part of the password.

**The .env file is already in .gitignore. These credentials will never be committed.**

---

## Step 5: Enable IMAP in Gmail Settings

1. In the new Gmail account, go to **Settings (gear icon) → See all settings**.
2. Click the **Forwarding and POP/IMAP** tab.
3. Under "IMAP Access", select **Enable IMAP**.
4. Click **Save Changes**.

---

## Step 6: Start the polling script in tmux

Open a terminal on your home laptop (not SSH, not work computer):

```bash
# Navigate to the project
cd "C:/Users/conno/The Playground/investment-research-copilot"

# Activate the venv
venv\Scripts\activate

# Start a tmux session (keeps running after terminal closes)
tmux new -s email-poll

# Start the poller
python email_interface/poll.py
```

You'll see output like:
```
[14:32:01 UTC] ===================================================
[14:32:01 UTC] CapitalContext Email Interface - Starting
[14:32:01 UTC] Polling: yourname.capitalcontext@gmail.com
[14:32:01 UTC] Interval: 300s (5 min)
[14:32:01 UTC] Log: .../logs/email_requests.jsonl
[14:32:01 UTC] ===================================================
[14:32:01 UTC] Checking inbox...
[14:32:02 UTC]   No new messages. Next check in 300s.
```

---

## Step 7: Detach tmux (leave it running)

Press `Ctrl+B`, then `D` to detach. The session keeps running.

To return to it later:
```bash
tmux attach -t email-poll
```

To stop it permanently:
```bash
tmux kill-session -t email-poll
```

---

## Step 8: Send a test request

From your personal Gmail (NOT work email):

**Subject:** `RESEARCH: NVDA`  
**Body:** (anything, or empty — the body is not used)

You'll get back:
1. A confirmation email within 30 seconds ("Request received, processing...")
2. A full research brief within 1–3 minutes

For a RAG query:

**Subject:** `QUERY: What are the main risks in PIMCO's income strategy?`

You'll get back a source-grounded answer with citations from your document corpus.

---

## Subject Line Reference

| Format | Routes to | Example |
|---|---|---|
| `RESEARCH: [ticker]` | Agentic research assistant | `RESEARCH: JPM` |
| `QUERY: [question]` | CapitalContext RAG | `QUERY: Compare BlackRock and PIMCO fee structures` |

- Matching is case-insensitive (`research:`, `RESEARCH:`, `Research:` all work)
- The ticker/question follows the colon with any amount of whitespace
- Emails with unrecognised subjects get a format hint reply

---

## Logs

Every request and response is logged to:
```
logs/email_requests.jsonl
```

Each line is a JSON object with: timestamp, event type, mode, query, sender, elapsed, cost, error.

---

## Restarting after laptop restart

The tmux session is lost on reboot. To restart:

```bash
cd "C:/Users/conno/The Playground/investment-research-copilot"
venv\Scripts\activate
tmux new -s email-poll
python email_interface/poll.py
```

Consider adding this to a startup script or Windows Task Scheduler if you want it to auto-start.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "GMAIL_POLLING_ADDRESS not set" | .env not updated | Add credentials to .env |
| "IMAP authentication failed" | Wrong App Password | Re-generate in Google Account settings |
| Confirmation received but no response | Agentic venv not set up | Run `pip install -r requirements.txt` in `agentic-research-assistant/` |
| "No module named agent.graph" | Agentic project path wrong | Check AGENTIC_ROOT in config.py |
| Laptop offline | - | Script can't run — responses won't arrive until laptop is back online |
