# monitor.py — Scans Gmail for replies from companies on our list
# Matches by sender domain, skips already-processed message IDs,
# classifies responses, updates CSV status accordingly.

import csv
import os
import base64
import json
from datetime import datetime
from urllib.parse import urlparse
from googleapiclient.discovery import build
from src.gmail.gmail_client import get_gmail_service, send_email
from config import PARTNERS_CLASSIFIED_FILE, CLAUDE_MODEL, ANTHROPIC_API_KEY
from anthropic import Anthropic

client = Anthropic(api_key=ANTHROPIC_API_KEY)

THANK_YOU_BODY = """Thank you for getting back to me. I appreciate you taking the time to respond.

Best,
Sebastian Russo
russo.sebastian@gmail.com
484-326-9897"""


def get_root_domain(url_or_email: str) -> str:
    """Extracts root domain from a URL or email address."""
    if "@" in url_or_email:
        domain = url_or_email.split("@")[-1].lower()
    else:
        domain = urlparse(url_or_email).netloc.lower()
    domain = domain.replace("www.", "")
    # Get root domain — last two parts (e.g. mail.tcs.com -> tcs.com)
    parts = domain.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain


def build_domain_map(partners: list[dict]) -> dict:
    """
    Builds a map of root domain -> partner record.
    Used to match incoming emails to companies.
    """
    domain_map = {}
    for p in partners:
        website = p.get("website", "")
        email = p.get("contact_email", "")
        for val in [website, email]:
            if val:
                domain = get_root_domain(val)
                if domain:
                    domain_map[domain] = p
    return domain_map


def get_message_body(service, message_id: str) -> str:
    """Fetches full message body text from Gmail."""
    try:
        msg = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full"
        ).execute()

        payload = msg.get("payload", {})

        # Walk MIME parts to find text/plain
        def extract_text(part):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            for p in part.get("parts", []):
                result = extract_text(p)
                if result:
                    return result
            return ""

        return extract_text(payload)

    except Exception as e:
        print(f"    Error fetching message body: {e}")
        return ""


def classify_response(subject: str, body: str, company_name: str) -> str:
    """
    Uses Claude to classify the response as:
    positive — interested, wants to connect, asking for more info
    negative — not hiring, not interested, no fit
    bounce   — delivery failure, auto-reply, out of office
    other    — unclear
    """
    prompt = f"""Classify this email response to a job outreach email sent to {company_name}.

Subject: {subject}
Body (first 500 chars): {body[:500]}

Respond with exactly one word — one of: positive, negative, bounce, other

Rules:
- positive: they're interested, want to connect, asking questions, forwarding to hiring manager
- negative: not hiring, no openings, not a fit, unsubscribe
- bounce: delivery failure, mailer-daemon, address not found, out of office auto-reply
- other: unclear or unrelated
"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip().lower()


def update_partner_status(partner: dict, status: str, message_id: str, notes: str = "") -> None:
    """Updates partner status and appends to status history."""
    now = datetime.now().isoformat()
    partner["status"] = status
    partner["last_reply"] = now
    partner["response_type"] = notes

    # Append to status history
    history = partner.get("status_history", "")
    entry = f"{status}:{now}"
    if notes:
        entry += f":{notes}"
    partner["status_history"] = f"{history}|{entry}" if history else entry

    # Log processed message ID so we never process it twice
    processed = partner.get("processed_message_ids", "")
    ids = processed.split("|") if processed else []
    if message_id not in ids:
        ids.append(message_id)
    partner["processed_message_ids"] = "|".join(ids)


def try_alternate_emails(service, partner: dict) -> bool:
    """
    Tries alternate email addresses when original bounced.
    Returns True if a fallback was found and queued.
    """
    website = partner.get("website", "")
    if not website:
        return False

    domain = urlparse(website).netloc.replace("www.", "")
    if not domain:
        return False

    alternates = [
        f"careers@{domain}",
        f"hr@{domain}",
        f"jobs@{domain}",
        f"recruiting@{domain}",
        f"talent@{domain}",
        f"contact@{domain}",
        f"hello@{domain}",
    ]

    # Skip the one we already tried
    already_tried = partner.get("contact_email", "")
    alternates = [a for a in alternates if a != already_tried]

    if alternates:
        partner["fallback_email"] = alternates[0]
        partner["fallback_queue"] = "|".join(alternates)
        return True

    return False


def run_monitor(auto_reply_negative: bool = True) -> dict:
    """
    Main monitor function. Scans inbox, classifies replies,
    updates CSV. Returns summary stats.
    """
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        print("Classified file not found.")
        return {}

    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    # Ensure new columns exist
    for p in partners:
        p.setdefault("last_reply", "")
        p.setdefault("response_type", "")
        p.setdefault("processed_message_ids", "")
        p.setdefault("fallback_email", "")
        p.setdefault("fallback_queue", "")

    domain_map = build_domain_map(partners)

    print("Authenticating with Gmail...")
    service = get_gmail_service()
    print("Authenticated. Scanning inbox...\n")

    # Fetch all inbox messages (not just unread)
    results = service.users().messages().list(
        userId="me",
        q="in:inbox",
        maxResults=200
    ).execute()

    messages = results.get("messages", [])
    print(f"Found {len(messages)} messages in inbox to check\n")

    stats = {
        "scanned": len(messages),
        "matched": 0,
        "positive": 0,
        "negative": 0,
        "bounce": 0,
        "other": 0,
        "already_processed": 0
    }

    for msg in messages:
        message_id = msg["id"]

        # Fetch headers
        full = service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        sender = headers.get("From", "")
        subject = headers.get("Subject", "")
        date = headers.get("Date", "")

        sender_email = sender.split("<")[-1].replace(">", "").strip()
        sender_domain = get_root_domain(sender_email) if "@" in sender_email else ""

        if sender_domain not in domain_map:
            continue

        partner = domain_map[sender_domain]
        stats["matched"] += 1

        # Skip if already processed
        processed_ids = partner.get("processed_message_ids", "").split("|")
        if message_id in processed_ids:
            stats["already_processed"] += 1
            continue

        print(f"Match: {partner['name']} — {subject[:60]}")

        # Get body for classification
        body = get_message_body(service, message_id)
        response_type = classify_response(subject, body, partner["name"])

        print(f"  Type: {response_type}")
        stats[response_type] = stats.get(response_type, 0) + 1

        if response_type == "positive":
            update_partner_status(partner, "needs_reply", message_id, "positive")
            print(f"  → Queued for your reply")

        elif response_type == "negative":
            update_partner_status(partner, "archived:rejected", message_id, "negative")
            if auto_reply_negative:
                try:
                    send_email(
                        service,
                        sender_email,
                        f"Re: {subject}",
                        THANK_YOU_BODY
                    )
                    print(f"  → Auto-replied thank you")
                except Exception as e:
                    print(f"  → Auto-reply failed: {e}")

        elif response_type == "bounce":
            has_fallback = try_alternate_emails(service, partner)
            if has_fallback:
                update_partner_status(partner, "bounce:retry_queued", message_id, "bounce")
                print(f"  → Fallback queued: {partner['fallback_email']}")
            else:
                update_partner_status(partner, "archived:bad_email", message_id, "bounce")
                print(f"  → No fallback, archived")

        else:
            update_partner_status(partner, "other", message_id, "other")
            print(f"  → Marked as other")

    _save_progress(partners)

    print(f"\n--- Scan Complete ---")
    print(f"Inbox messages scanned: {stats['scanned']}")
    print(f"Company matches found:  {stats['matched']}")
    print(f"Positive:               {stats.get('positive', 0)}")
    print(f"Negative:               {stats.get('negative', 0)}")
    print(f"Bounce:                 {stats.get('bounce', 0)}")
    print(f"Already processed:      {stats['already_processed']}")

    return stats


def send_fallback_emails() -> None:
    """
    Sends emails to fallback addresses for bounced companies.
    Call this after run_monitor() to retry bounced emails.
    """
    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    to_retry = [p for p in partners if p.get("status") == "bounce:retry_queued"]

    if not to_retry:
        print("No bounced emails to retry.")
        return

    print(f"Retrying {len(to_retry)} bounced emails...\n")
    service = get_gmail_service()

    from src.gmail.sender import parse_email_file

    for partner in to_retry:
        fallback = partner.get("fallback_email", "")
        if not fallback:
            continue

        email_data = parse_email_file(partner.get("email_file", ""))
        if not email_data:
            continue

        print(f"Retrying {partner['name']} → {fallback}")
        try:
            send_email(service, fallback, email_data["subject"], email_data["body"])
            partner["contact_email"] = fallback
            now = datetime.now().isoformat()
            partner["status"] = "sent"
            history = partner.get("status_history", "")
            partner["status_history"] = f"{history}|sent_fallback:{now}"
            print(f"  ✓ Sent")
        except Exception as e:
            # Pop this fallback and try next one
            queue = partner.get("fallback_queue", "").split("|")
            queue = [q for q in queue if q != fallback]
            if queue:
                partner["fallback_email"] = queue[0]
                partner["fallback_queue"] = "|".join(queue)
                print(f"  ✗ Failed, next fallback: {queue[0]}")
            else:
                partner["status"] = "archived:bad_email"
                print(f"  ✗ All fallbacks exhausted, archived")

    _save_progress(partners)
    print("\nDone.")


def _save_progress(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    run_monitor()
