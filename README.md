# Telegram Checker Bot

Python Telegram bot that runs validation checks for URLs, IPs, emails, hashes, and more. It keeps a local SQLite database with user statistics, offers a full admin toolset, and reads onboarding prompts from `bot_details.txt`.

## Features
- `/check <text>` analyzes URLs, IP addresses, emails, hashes, and generic strings.
- Smart fallback: every plain text message triggers the same analysis.
- Inline mode support (`@YourBot query`) for quick checks in other chats.
- Persistent SQLite storage for users, check history, and audit trails.
- Admin commands: `/stats`, `/recent`, `/broadcast`, `/ban`, `/unban`, `/banned`, `/reload`.
- Customizable welcome/help text via `bot_details.txt`.
- Comprehensive error handling and logging.

## Setup
1. `python -m venv .venv && source .venv/bin/activate` (or use your preferred environment).
2. `pip install -r requirements.txt`.
3. Create a `.env` file if you prefer not to modify the script directly:
   ```
   TELEGRAM_BOT_TOKEN=8567935515:AAHwNAtuag78cB6_9Mg3vz8EZe14AG7CI6A
   TELEGRAM_ADMIN_IDS=8149429097
   ```
   To use the embedded token without a `.env` file, export `ALLOW_INLINE_TOKEN=1`.
4. (Optional) Edit `bot_details.txt` with your own copy for `/start` and `/help`.

## Running the Bot
```bash
python app.py
```

## Admin Quick Reference
- `/stats` – Show totals, banned users, and uptime.
- `/recent [limit]` – Display the latest check logs.
- `/broadcast <message>` – Send a message to every user (or reply to forward).
- `/ban <user_id>` / `/unban <user_id>` – Manage user access (replying works too).
- `/banned` – List all banned users.
- `/reload` – Refresh cached `bot_details.txt`.

## Deployment Notes
- Runs well on regular PCs, VPS, or RDP environments.
- Requires continuous execution to handle Telegram updates (polling mode).
- Ensure outbound HTTPS access for URL checks.
