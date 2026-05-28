# sender.py — Sends the drafted emails via Gmail API
# Reads partners_classified.csv, sends each drafted email,
# updates status to 'sent' and logs the timestamp.

import csv
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
from src.gmail.gmail_client import get_gmail_service, send_email
from config import (
    PARTNERS_CLASSIFIED_FILE,
    OUTPUT_EMAILS_DIR,
    MATCH_HAS_CAREERS, MATCH_NO_CAREERS
)

load_dotenv()


def parse_email_file(filepath: str) -> dict:
    """
    Reads a drafted .txt email file and returns subject + body.
    """
    if not filepath or not os.path.exists(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    subject = ""
    body_lines = []
    in_body = False

    for line in lines:
        if line.startswith("SUBJECT:"):
            subject = line[8:].strip()
        elif line.startswith("-" * 10):
            in_body = True
        elif in_body:
            body_lines.append(line)

    return {
        "subject": subject,
        "body": "".join(body_lines).strip()
    }


def run_sender(sample_mode: bool = False, sample_size: int = 5):
    """
    Sends all drafted emails via Gmail.
    sample_mode=True sends only sample_size emails for review.
    """
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        print("Classified file not found. Run phases 3 and 4 first.")
        return

    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    # Add status columns if missing
    for p in partners:
        p.setdefault("status", "pending")
        p.setdefault("sent_at", "")
        p.setdefault("status_history", "")

    # Filter to sendable
    to_send = [
        p for p in partners
        if p.get("email_drafted") == "yes"
        and p.get("classification") in [MATCH_HAS_CAREERS, MATCH_NO_CAREERS]
        and p.get("status") in ["pending", "scraped"]
    ]

    if sample_mode:
        to_send = to_send[:sample_size]
        print(f"SAMPLE MODE — sending {len(to_send)} emails for review\n")
    else:
        print(f"Sending {len(to_send)} emails...\n")

    print("Authenticating with Gmail...")
    service = get_gmail_service()
    print("Authenticated.\n")

    sent = failed = 0

    for i, partner in enumerate(to_send):
        email_data = parse_email_file(partner.get("email_file", ""))

        if not email_data.get("subject") or not email_data.get("body"):
            print(f"[{i+1}] Skipping {partner['name']} — email file missing or empty")
            failed += 1
            continue

        to_addr = partner.get("contact_email", "")
        if not to_addr:
            print(f"[{i+1}] Skipping {partner['name']} — no email address")
            failed += 1
            continue

        print(f"[{i+1}/{len(to_send)}] Sending to {partner['name']} <{to_addr}>")

        try:
            send_email(service, to_addr, email_data["subject"], email_data["body"])

            # Update partner record
            now = datetime.now().isoformat()
            partner["status"] = "sent"
            partner["sent_at"] = now
            partner["status_history"] = f"sent:{now}"

            sent += 1
            print(f"    ✓ Sent")

        except Exception as e:
            error_str = str(e)
            print(f"    ✗ Failed: {e}")
            failed += 1

            # Gmail daily limit hit — stop gracefully
            if "rateLimitExceeded" in error_str or "429" in error_str:
                print("\n⚠️  Gmail daily sending limit reached. Run again tomorrow to continue.")
                _save_progress(partners)
                return

        # Save progress every 10
        if (sent + failed) % 10 == 0:
            _save_progress(partners)

        # Small delay — don't hammer Gmail API
        time.sleep(1.5)

    _save_progress(partners)

    print(f"\n--- Send Complete ---")
    print(f"Sent:   {sent}")
    print(f"Failed: {failed}")


def _save_progress(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Send sample of 5 emails only")
    parser.add_argument("--sample-size", type=int, default=5)
    args = parser.parse_args()
    run_sender(sample_mode=args.sample, sample_size=args.sample_size)
