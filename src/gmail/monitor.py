import csv
import os
import base64
import re
import json
from datetime import datetime, timezone
from urllib.parse import urlparse
from src.gmail.gmail_client import get_gmail_service, send_email
from config import PARTNERS_CLASSIFIED_FILE, CLAUDE_MODEL, ANTHROPIC_API_KEY
from anthropic import Anthropic

client = Anthropic(api_key=ANTHROPIC_API_KEY)


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
    return {p.get("contact_email", "").lower(): p for p in partners if p.get("contact_email")}


def build_name_map(partners: list[dict]) -> dict:
    return {p.get("name", "").lower(): p for p in partners if p.get("name")}


def get_message_body(service, message_id: str) -> str:
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
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
    emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', body)
    for email in emails:
        domain = email.split("@")[1].lower()
        if "google" not in domain and "gmail" not in domain and "mailer" not in domain:
            return email.lower()
    return ""


def parse_company_from_subject(subject: str) -> str:
    marker = "Exploring Opportunities at "
    if marker in subject:
        return subject.split(marker)[-1].strip().lower()
    return ""


def classify_response(subject: str, body: str, company_name: str) -> dict:
    prompt = f"""You are analyzing an email reply to a job outreach sent to {company_name}.

Subject: {subject}
Body: {body[:1500]}

Respond ONLY with a JSON object, no preamble, no markdown:
{{
  "response_type": "positive_meeting" | "positive_apply" | "positive_general" | "negative_no_fit" | "negative_no_opening" | "bounce" | "other",
  "next_action": "schedule_meeting" | "submit_application" | "send_reply" | "follow_up_in_30_days" | "follow_up_next_search" | "none",
  "apply_url": "url if they provided an application link, else empty string",
  "contact_name": "name of person who replied if found in signature, else empty string",
  "contact_title": "their job title if found, else empty string",
  "summary": "one sentence summary of what they said"
}}

Classification rules:
- positive_meeting: they want to schedule a call, interview, or meeting
- positive_apply: they sent a link to apply through their site or ATS
- positive_general: interested or encouraging but no specific next step
- negative_no_fit: explicitly said not a match for their needs or tech stack
- negative_no_opening: good fit but no current openings, keep in mind for future
- bounce: hard delivery failure only — address not found, mailbox full, 550 errors
- other: auto-reply, OOO, ticket confirmation, welcome email, system notification

Next action rules:
- schedule_meeting → if positive_meeting
- submit_application → if positive_apply
- send_reply → if positive_general
- follow_up_in_30_days → if negative_no_opening
- follow_up_next_search → if negative_no_fit but company seems like good long term fit
- none → if negative_no_fit and no future potential, or bounce, or other

When in doubt between bounce and other, choose other.
Only choose positive or negative if it's clearly a real human response.
"""
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        return json.loads(raw)
    except Exception as e:
        print(f"    Classification error: {e}")
        return {
            "response_type": "other",
            "next_action": "none",
            "apply_url": "",
            "contact_name": "",
            "contact_title": "",
            "summary": ""
        }


def log_activity(partners: list[dict], message: str) -> None:
    """Appends to a global activity log stored in a sidecar file."""
    log_path = os.path.join(os.path.dirname(PARTNERS_CLASSIFIED_FILE), "activity_log.jsonl")
    entry = {"ts": datetime.now().isoformat(), "msg": message}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def update_partner_status(partner: dict, status: str, message_id: str,
                          classification: dict = None) -> None:
    now = datetime.now().isoformat()
    partner["status"] = status
    partner["last_reply"] = now

    if classification:
        partner["response_type"] = classification.get("response_type", "")
        partner["next_action"] = classification.get("next_action", "")
        partner["apply_url"] = classification.get("apply_url", "")
        partner["email_thread"] = classification.get("summary", "")

        contact_name = classification.get("contact_name", "")
        contact_title = classification.get("contact_title", "")
        if contact_name:
            add_contact(partner, contact_name, contact_title,
                       partner.get("contact_email", ""), "replied to outreach")

        # Calculate response time in days
        sent_at = partner.get("sent_at", "")
        if sent_at:
            try:
                sent_dt = datetime.fromisoformat(sent_at)
                now_dt = datetime.now()
                days = (now_dt - sent_dt).days
                partner["response_rate_days"] = str(days)
            except Exception:
                pass

    history = partner.get("status_history", "")
    entry = f"{status}:{now}"
    partner["status_history"] = f"{history}|{entry}" if history else entry

    processed = partner.get("processed_message_ids", "")
    ids = processed.split("|") if processed else []
    if message_id not in ids:
        ids.append(message_id)
    partner["processed_message_ids"] = "|".join(ids)


def add_contact(partner: dict, name: str, title: str, email: str, notes: str) -> None:
    try:
        contacts = json.loads(partner.get("contacts", "[]") or "[]")
    except Exception:
        contacts = []
    if any(c.get("name", "").lower() == name.lower() for c in contacts):
        return
    contacts.append({
        "name": name, "title": title, "email": email,
        "notes": notes, "date_added": datetime.now().strftime("%Y-%m-%d")
    })
    partner["contacts"] = json.dumps(contacts)


def try_alternate_emails(partner: dict) -> bool:
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
    has_fallback = try_alternate_emails(partner)
    if has_fallback:
        update_partner_status(partner, "bounce:retry_queued", message_id)
        print(f"  → Fallback queued: {partner['fallback_email']}")
    else:
        update_partner_status(partner, "archived:bad_email", message_id)
        print(f"  → No fallback, archived")


def get_status_for_response_type(response_type: str) -> str:
    mapping = {
        "positive_meeting":    "meeting_requested",
        "positive_apply":      "apply_link_received",
        "positive_general":    "needs_reply",
        "negative_no_fit":     "archived:rejected",
        "negative_no_opening": "keep_warm",
        "bounce":              "bounce:retry_queued",
        "other":               None
    }
    return mapping.get(response_type)


def scan_sent_folder(service, partners: list[dict], email_map: dict, name_map: dict) -> int:
    """
    Scans Sent folder to catch manually sent emails and update sent_at.
    Returns count of newly matched sent emails.
    """
    matched = 0
    try:
        results = service.users().messages().list(
            userId="me",
            q='in:sent subject:"Amazon Connect Developer"',
            maxResults=500
        ).execute()
        messages = results.get("messages", [])

        for msg in messages:
            full = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["To", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
            to_addr = headers.get("To", "").split("<")[-1].replace(">", "").strip().lower()
            subject = headers.get("Subject", "")
            date_str = headers.get("Date", "")

            partner = email_map.get(to_addr)
            if not partner:
                company_name = parse_company_from_subject(subject)
                if company_name:
                    for name, p in name_map.items():
                        if name in company_name or company_name in name:
                            partner = p
                            break

            if not partner:
                continue

            # Mark as sent if not already
            if not partner.get("sent_at"):
                partner["sent_at"] = date_str
                if partner.get("status") in ["scraped", "pending"]:
                    partner["status"] = "sent"
                partner["manually_sent"] = "yes"
                matched += 1

    except Exception as e:
        print(f"  Sent folder scan error: {e}")

    return matched


def run_monitor() -> dict:
    """
    Scans inbox and sent folder.
    Classifies replies. Does NOT send any emails.
    Returns stats dict.
    """
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        print("Classified file not found.")
        return {}

    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    new_cols = {
        "last_reply": "", "response_type": "", "next_action": "",
        "next_action_date": "", "apply_url": "", "email_thread": "",
        "contact_name": "", "meeting_notes": "", "contacts": "[]",
        "processed_message_ids": "", "fallback_email": "", "fallback_queue": "",
        "notes": "", "tags": "", "manually_sent": "", "response_rate_days": "",
        "sent_at": ""
    }
    for p in partners:
        for col, default in new_cols.items():
            p.setdefault(col, default)

    domain_map = build_domain_map(partners)
    email_map = build_email_map(partners)
    name_map = build_name_map(partners)

    print("Authenticating with Gmail...")
    service = get_gmail_service()
    print("Authenticated.\n")

    # Scan sent folder first
    print("Scanning Sent folder for manually sent emails...")
    sent_matched = scan_sent_folder(service, partners, email_map, name_map)
    print(f"  {sent_matched} manually sent emails detected\n")

    # Scan inbox
    print("Scanning inbox...")
    results = service.users().messages().list(
        userId="me", q="in:inbox", maxResults=500
    ).execute()
    messages = results.get("messages", [])
    print(f"Found {len(messages)} inbox messages\n")

    stats = {
        "scanned": len(messages),
        "matched": 0,
        "positive_meeting": 0,
        "positive_apply": 0,
        "positive_general": 0,
        "negative_no_fit": 0,
        "negative_no_opening": 0,
        "bounce": 0,
        "other": 0,
        "already_processed": 0,
        "sent_folder_matched": sent_matched
    }

    for msg in messages:
        message_id = msg["id"]

        full = service.users().messages().get(
            userId="me", id=message_id, format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        sender = headers.get("From", "")
        subject = headers.get("Subject", "")
        sender_lower = sender.lower()
        sender_email = sender.split("<")[-1].replace(">", "").strip()

        # Path 1: mailer-daemon bounce
        if any(x in sender_lower for x in ["mailer-daemon", "postmaster", "mail delivery"]):
            body = get_message_body(service, message_id)
            recipient = parse_bounce_recipient(body)

            partner = None
            if recipient and recipient in email_map:
                partner = email_map[recipient]
            else:
                company_name = parse_company_from_subject(subject)
                if company_name:
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
            log_activity(partners, f"Bounce detected: {partner['name']}")
            continue

        # Path 2: real reply from company domain
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
        classification = classify_response(subject, body, partner["name"])
        response_type = classification.get("response_type", "other")

        print(f"  Type: {response_type}")
        if classification.get("next_action"):
            print(f"  Next: {classification['next_action']}")
        if classification.get("contact_name"):
            print(f"  Contact: {classification['contact_name']}")
        if classification.get("apply_url"):
            print(f"  Apply: {classification['apply_url']}")

        stats[response_type] = stats.get(response_type, 0) + 1

        new_status = get_status_for_response_type(response_type)

        if new_status is None:
            processed = partner.get("processed_message_ids", "")
            ids = processed.split("|") if processed else []
            if message_id not in ids:
                ids.append(message_id)
            partner["processed_message_ids"] = "|".join(ids)
            print(f"  → Ignored")
            continue

        update_partner_status(partner, new_status, message_id, classification)
        log_activity(partners, f"{response_type}: {partner['name']} — {classification.get('summary','')[:60]}")
        print(f"  → {new_status}")

    _save_progress(partners)

    print(f"\n--- Scan Complete ---")
    print(f"Scanned:          {stats['scanned']}")
    print(f"Matched:          {stats['matched']}")
    print(f"Meeting requests: {stats.get('positive_meeting', 0)}")
    print(f"Apply links:      {stats.get('positive_apply', 0)}")
    print(f"General positive: {stats.get('positive_general', 0)}")
    print(f"No fit:           {stats.get('negative_no_fit', 0)}")
    print(f"No opening:       {stats.get('negative_no_opening', 0)}")
    print(f"Bounced:          {stats.get('bounce', 0)}")
    print(f"Already processed:{stats['already_processed']}")

    return stats


def send_fallback_emails(batch_size: int = 50) -> dict:
    """Sends next batch of fallback emails for bounced companies."""
    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    to_retry = [p for p in partners if p.get("status") == "bounce:retry_queued"]

    if not to_retry:
        print("No bounced emails to retry.")
        return {"sent": 0, "failed": 0, "remaining": 0}

    batch = to_retry[:batch_size]
    remaining_after = len(to_retry) - len(batch)
    print(f"Retrying {len(batch)} bounced emails (batch of {batch_size})...\n")

    service = get_gmail_service()
    from src.gmail.sender import parse_email_file

    sent = failed = 0

    for partner in batch:
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
            log_activity(partners, f"Fallback sent: {partner['name']} → {fallback}")
            sent += 1
            print(f"  ✓ Sent")
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rateLimitExceeded" in error_str:
                print(f"\n⚠️  Gmail daily limit hit.")
                _save_progress(partners)
                return {"sent": sent, "failed": failed, "remaining": len(to_retry) - sent}
            queue = partner.get("fallback_queue", "").split("|")
            queue = [q for q in queue if q != fallback]
            if queue:
                partner["fallback_email"] = queue[0]
                partner["fallback_queue"] = "|".join(queue)
                print(f"  ✗ Bad address, next fallback: {queue[0]}")
            else:
                partner["status"] = "archived:bad_email"
                print(f"  ✗ All fallbacks exhausted")
            failed += 1

    _save_progress(partners)
    print(f"\nDone. Sent: {sent}, Failed: {failed}, Remaining: {remaining_after}")
    return {"sent": sent, "failed": failed, "remaining": remaining_after}


def send_thankyou_batch(batch_size: int = 50) -> dict:
    """Sends thank you replies to negative_no_fit companies."""
    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    to_send = [
        p for p in partners
        if p.get("response_type") == "negative_no_fit"
        and p.get("status") == "archived:rejected"
        and not p.get("thankyou_sent")
    ]

    if not to_send:
        return {"sent": 0, "remaining": 0}

    batch = to_send[:batch_size]
    service = get_gmail_service()
    sent = 0

    BODY = """Thank you for getting back to me. I appreciate you taking the time to respond.

Best,
Sebastian Russo
russo.sebastian@gmail.com
484-326-9897"""

    for partner in batch:
        email = partner.get("contact_email", "")
        if not email:
            continue
        try:
            subject = f"Re: Amazon Connect Developer — Exploring Opportunities at {partner['name']}"
            send_email(service, email, subject, BODY)
            partner["thankyou_sent"] = "yes"
            log_activity(partners, f"Thank you sent: {partner['name']}")
            sent += 1
        except Exception as e:
            if "429" in str(e):
                break

    _save_progress(partners)
    return {"sent": sent, "remaining": len(to_send) - sent}


def send_keepwarm_batch(batch_size: int = 50) -> dict:
    """Sends keep warm acknowledgment to negative_no_opening companies."""
    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    to_send = [
        p for p in partners
        if p.get("response_type") == "negative_no_opening"
        and p.get("status") == "keep_warm"
        and not p.get("keepwarm_sent")
    ]

    if not to_send:
        return {"sent": 0, "remaining": 0}

    batch = to_send[:batch_size]
    service = get_gmail_service()
    sent = 0

    BODY = """Thank you for letting me know. I completely understand — timing is everything in hiring.

I'd love to stay on your radar for when the right opportunity opens up. I'll plan to check back in a few months, but please don't hesitate to reach out if something comes up in the meantime.

Best,
Sebastian Russo
russo.sebastian@gmail.com
484-326-9897
linkedin.com/in/sebastian-russo-2054565a"""

    for partner in batch:
        email = partner.get("contact_email", "")
        if not email:
            continue
        try:
            subject = f"Re: Amazon Connect Developer — Exploring Opportunities at {partner['name']}"
            send_email(service, email, subject, BODY)
            partner["keepwarm_sent"] = "yes"
            log_activity(partners, f"Keep warm sent: {partner['name']}")
            sent += 1
        except Exception as e:
            if "429" in str(e):
                break

    _save_progress(partners)
    return {"sent": sent, "remaining": len(to_send) - sent}


def archive_no_response(days: int = 30) -> dict:
    """Marks companies with no reply after N days as archived:no_response."""
    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    now = datetime.now()
    archived = 0

    for p in partners:
        if p.get("status") != "sent":
            continue
        sent_at = p.get("sent_at", "")
        if not sent_at:
            continue
        try:
            sent_dt = datetime.fromisoformat(sent_at)
            if (now - sent_dt).days >= days:
                p["status"] = "archived:no_response"
                history = p.get("status_history", "")
                p["status_history"] = f"{history}|archived:no_response:{now.isoformat()}"
                archived += 1
        except Exception:
            continue

    _save_progress(partners)
    return {"archived": archived}


def get_activity_log(limit: int = 20) -> list:
    log_path = os.path.join(os.path.dirname(PARTNERS_CLASSIFIED_FILE), "activity_log.jsonl")
    if not os.path.exists(log_path):
        return []
    entries = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                continue
    return list(reversed(entries))[:limit]


def _save_progress(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    run_monitor()
