import csv
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from src.gmail.gmail_client import get_gmail_service, send_email
from config import PARTNERS_CLASSIFIED_FILE, MATCH_HAS_CAREERS, MATCH_NO_CAREERS

load_dotenv()


def parse_email_file(filepath: str) -> dict:
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
    return {"subject": subject, "body": "".join(body_lines).strip()}


def send_pending_batch(batch_size: int = 50) -> dict:
    """
    Sends next batch of pending emails.
    Returns stats dict with sent, failed, remaining.
    """
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        return {"sent": 0, "failed": 0, "remaining": 0, "error": "File not found"}

    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    for p in partners:
        p.setdefault("status", "pending")
        p.setdefault("sent_at", "")
        p.setdefault("status_history", "")
        p.setdefault("manually_sent", "")

    to_send = [
        p for p in partners
        if p.get("email_drafted") == "yes"
        and p.get("classification") in [MATCH_HAS_CAREERS, MATCH_NO_CAREERS]
        and p.get("status") in ["pending", "scraped"]
    ]

    remaining_total = len(to_send)
    if remaining_total == 0:
        return {"sent": 0, "failed": 0, "remaining": 0}

    batch = to_send[:batch_size]
    print(f"Sending batch of {len(batch)} (total remaining: {remaining_total})...")

    service = get_gmail_service()
    sent = failed = 0

    for i, partner in enumerate(batch):
        email_data = parse_email_file(partner.get("email_file", ""))
        if not email_data.get("subject") or not email_data.get("body"):
            failed += 1
            continue

        to_addr = partner.get("contact_email", "")
        if not to_addr:
            failed += 1
            continue

        print(f"[{i+1}/{len(batch)}] {partner['name']} → {to_addr}")

        try:
            send_email(service, to_addr, email_data["subject"], email_data["body"])
            now = datetime.now().isoformat()
            partner["status"] = "sent"
            partner["sent_at"] = now
            history = partner.get("status_history", "")
            partner["status_history"] = f"{history}|sent:{now}" if history else f"sent:{now}"
            sent += 1
            print(f"  ✓ Sent")
        except Exception as e:
            error_str = str(e)
            print(f"  ✗ Failed: {e}")
            if "429" in error_str or "rateLimitExceeded" in error_str:
                print(f"\n⚠️  Gmail daily limit hit. Try again tomorrow.")
                _save_progress(partners)
                return {"sent": sent, "failed": failed,
                        "remaining": remaining_total - sent, "rate_limited": True}
            failed += 1

        if (sent + failed) % 10 == 0:
            _save_progress(partners)

        time.sleep(1.5)

    _save_progress(partners)
    remaining_after = remaining_total - sent
    print(f"\nBatch done. Sent: {sent}, Failed: {failed}, Remaining: {remaining_after}")
    return {"sent": sent, "failed": failed, "remaining": remaining_after}


def _save_progress(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    size = args.sample_size if args.sample else args.batch_size
    send_pending_batch(batch_size=size)
