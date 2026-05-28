import csv
import os
import base64
import re
from datetime import datetime
from urllib.parse import urlparse
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
    if "@" in url_or_email:
        domain = url_or_email.split("@")[-1].lower()
    else:
        domain = urlparse(url_or_email).netloc.lower()
    domain = domain.replace("www.", "")
    parts = domain.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain


def build_domain_map(partners: list[dict]) -> dict:
    domain_map = {}
    for p in partners:
        for val in [p.get("website", ""), p.get("contact_email", "")]:
            if val:
                domain = get_root_domain(val)
                if domain:
                    domain_map[domain] = p
    return domain_map


def build_email_map(partners: list[dict]) -> dict:
    """Maps contact_email -> partner for mailer-daemon bounce matching."""
    return {p.get("contact_email", "").lower(): p for p in partners if p.get("contact_email")}


def build_name_map(partners: list[dict]) -> dict:
    """Maps lowercase company name -> partner for subject line matching."""
    return {p.get("name", "").lower(): p for p in partners if p.get("name")}


def get_message_body(service, message_id: str) -> str:
    try:
        msg = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full"
        ).execute()

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

        return extract_text(msg.get("payload", {}))
    except Exception as e:
        print(f"    Error fetching body: {e}")
        return ""


def parse_bounce_recipient(body: str) -> str:
    """Extracts original recipient email from a mailer-daemon bounce body."""
    emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', body)
    for email in emails:
        domain = email.split("@")[1].lower()
        if "google" not in domain and "gmail" not in domain and "mailer" not in domain:
            return email.lower()
    return ""


def parse_company_from_subject(subject: str) -> str:
    """
    Extracts company name from our subject line pattern:
    'Amazon Connect Developer — Exploring Opportunities at COMPANY'
    """
    marker = "Exploring Opportunities at "
    if marker in subject:
        return subject.split(marker)[-1].strip().lower()
    return ""


def classify_response(subject: str, body: str, company_name: str) -> str:
    prompt = f"""Classify this email response to a job outreach email sent to {company_name}.

Subject: {subject}
Body (first 500 chars): {body[:500]}

Respond with exactly one word — one of: positive, negative, bounce, other

Strict rules:
- bounce: ONLY for hard delivery failures — "address not found", "user does not exist", "undeliverable", "550", "mailbox not found". NOT for out-of-office or auto-replies.
- positive: a real human replied with genuine interest — wants to connect, asking questions, forwarding to hiring manager, requesting resume
- negative: a real human replied saying not hiring, no openings, not a fit, please remove me
- other: everything else — out of office, auto-reply, ticket confirmation, welcome email, support portal, OOO, "we received your email", system notifications, activation emails

When in doubt between bounce and other, choose other.
When in doubt between positive and other, choose other.
Only choose positive or negative if it's clearly a real human response.
"""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip().lower()


def update_partner_status(partner: dict, status: str, message_id: str, notes: str = "") -> None:
    now = datetime.now().isoformat()
    partner["status"] = status
    partner["last_reply"] = now
    partner["response_type"] = notes
    history = partner.get("status_history", "")
    entry = f"{status}:{now}" + (f":{notes}" if notes else "")
    partner["status_history"] = f"{history}|{entry}" if history else entry
    processed = partner.get("processed_message_ids", "")
    ids = processed.split("|") if processed else []
    if message_id not in ids:
        ids.append(message_id)
    partner["processed_message_ids"] = "|".join(ids)


def try_alternate_emails(service, partner: dict) -> bool:
    website = partner.get("website", "")
    if not website:
        return False
    domain = urlparse(website).netloc.replace("www.", "")
    if not domain:
        return False
    alternates = [
        f"careers@{domain}", f"hr@{domain}", f"jobs@{domain}",
        f"recruiting@{domain}", f"talent@{domain}",
        f"contact@{domain}", f"hello@{domain}",
    ]
    already_tried = partner.get("contact_email", "")
    tried_list = partner.get("fallback_queue", "")
    alternates = [a for a in alternates if a != already_tried and a not in tried_list]
    if alternates:
        partner["fallback_email"] = alternates[0]
        partner["fallback_queue"] = "|".join(alternates)
        return True
    return False


def handle_bounce(partner: dict, message_id: str) -> None:
    has_fallback = try_alternate_emails(None, partner)
    if has_fallback:
        update_partner_status(partner, "bounce:retry_queued", message_id, "bounce")
        print(f"  → Fallback queued: {partner['fallback_email']}")
    else:
        update_partner_status(partner, "archived:bad_email", message_id, "bounce")
        print(f"  → No fallback, archived")


def run_monitor(auto_reply_negative: bool = True) -> dict:
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        print("Classified file not found.")
        return {}

    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    for p in partners:
        p.setdefault("last_reply", "")
        p.setdefault("response_type", "")
        p.setdefault("processed_message_ids", "")
        p.setdefault("fallback_email", "")
        p.setdefault("fallback_queue", "")

    domain_map = build_domain_map(partners)
    email_map = build_email_map(partners)
    name_map = build_name_map(partners)

    print("Authenticating with Gmail...")
    service = get_gmail_service()
    print("Authenticated. Scanning inbox...\n")

    results = service.users().messages().list(
        userId="me",
        q="in:inbox",
        maxResults=500
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

        full = service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        sender = headers.get("From", "")
        subject = headers.get("Subject", "")

        sender_email = sender.split("<")[-1].replace(">", "").strip()
        sender_lower = sender.lower()

        # --- Path 1: mailer-daemon bounce ---
        if "mailer-daemon" in sender_lower or "postmaster" in sender_lower or "mail delivery" in sender_lower:
            # Try to match by original recipient email in body
            body = get_message_body(service, message_id)
            recipient = parse_bounce_recipient(body)

            partner = None
            if recipient and recipient in email_map:
                partner = email_map[recipient]
            else:
                # Fall back to company name in subject line
                company_name = parse_company_from_subject(subject)
                if company_name:
                    # Fuzzy match — find partner whose name is contained in subject
                    for name, p in name_map.items():
                        if name in company_name or company_name in name:
                            partner = p
                            break

            if not partner:
                continue

            stats["matched"] += 1
            processed_ids = partner.get("processed_message_ids", "").split("|")
            if message_id in processed_ids:
                stats["already_processed"] += 1
                continue

            print(f"Bounce: {partner['name']} — {recipient or subject[:50]}")
            handle_bounce(partner, message_id)
            stats["bounce"] += 1
            continue

        # --- Path 2: real reply from company domain ---
        sender_domain = get_root_domain(sender_email) if "@" in sender_email else ""
        if sender_domain not in domain_map:
            continue

        partner = domain_map[sender_domain]
        stats["matched"] += 1

        processed_ids = partner.get("processed_message_ids", "").split("|")
        if message_id in processed_ids:
            stats["already_processed"] += 1
            continue

        print(f"Match: {partner['name']} — {subject[:60]}")

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
                    send_email(service, sender_email, f"Re: {subject}", THANK_YOU_BODY)
                    print(f"  → Auto-replied thank you")
                except Exception as e:
                    print(f"  → Auto-reply failed: {e}")

        elif response_type == "bounce":
            handle_bounce(partner, message_id)
            stats["bounce"] += 1

        else:
            processed = partner.get("processed_message_ids", "")
            ids = processed.split("|") if processed else []
            if message_id not in ids:
                ids.append(message_id)
            partner["processed_message_ids"] = "|".join(ids)
            print(f"  → Ignored (auto-reply/notification)")

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
            error_str = str(e)

            # Rate limit — stop everything, don't burn fallbacks
            if "429" in error_str or "rateLimitExceeded" in error_str:
                print(f"\n⚠️  Gmail daily limit hit. Run 5c again tomorrow.")
                _save_progress(partners)
                return

            # Real failure — try next fallback
            queue = partner.get("fallback_queue", "").split("|")
            queue = [q for q in queue if q != fallback]
            if queue:
                partner["fallback_email"] = queue[0]
                partner["fallback_queue"] = "|".join(queue)
                print(f"  ✗ Bad address, next fallback: {queue[0]}")
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
