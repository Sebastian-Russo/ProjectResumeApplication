# email_writer.py — Uses Claude to draft outreach emails for each matched company
# Think of this like a ghostwriter who reads your resume and the company's job post,
# then writes a tailored letter on your behalf. For direct matches they reference
# the specific role; for general matches they write a warm cold-outreach email.
# You review and approve before anything gets sent.

import csv
import json
import os
import time
from anthropic import Anthropic
from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    PARTNERS_CLASSIFIED_FILE, EMAILS_DRAFTED_FILE,
    OUTPUT_EMAILS_DIR, PROFILE_DIR,
    MATCH_DIRECT, MATCH_GENERAL
)

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def load_profile() -> str:
    profile_path = os.path.join(PROFILE_DIR, "profile.txt")
    with open(profile_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def draft_email(partner: dict, profile: str) -> dict:
    """
    Drafts a subject line + email body for one company.
    Returns dict with: subject, body, email_to
    """

    classification = partner.get("classification", "")
    company_name = partner.get("name", "the company")
    jobs_found = partner.get("jobs_found", "")
    relevant_jobs = partner.get("relevant_jobs", "")
    contact_email = partner.get("contact_email", "")
    description = partner.get("description", "")

    # Tell Claude which mode we're in so it adjusts the angle
    if classification == MATCH_DIRECT:
        mode_instruction = f"""
This company has specific relevant job listings: {relevant_jobs or jobs_found}
Write a targeted application email referencing the specific role(s) found.
Open by naming the role you're applying for. Be direct and confident.
"""
    else:
        mode_instruction = f"""
No specific job listing was found, but this company works with Amazon Connect / AWS.
Write a warm cold-outreach email expressing interest in potential opportunities.
Don't mention a specific role — instead express interest in their Connect/AWS work
and open the door for a conversation.
"""

    prompt = f"""You are writing a job outreach email on behalf of a candidate.

--- CANDIDATE PROFILE ---
{profile}
--- END PROFILE ---

--- COMPANY ---
Name: {company_name}
Description: {description}
Contact: {contact_email}
--- END COMPANY ---

--- INSTRUCTIONS ---
{mode_instruction}

Guidelines:
- Subject line should be specific, not generic ("Experienced Amazon Connect Developer — [Role]" not "Job Inquiry")
- 3-4 short paragraphs max
- Paragraph 1: who you are and why you're reaching out (mention the role or their Connect work)
- Paragraph 2: most relevant experience for THIS company (pick from profile — don't list everything)
- Paragraph 3: what you bring / why it's a fit
- Paragraph 4: brief call to action — ask for a call or to send more materials
- Sign off as Sebastian Russo with email russo.sebastian@gmail.com
- Professional but human — not stiff corporate speak
- Do NOT use filler phrases like "I am writing to express my interest" or "I came across your posting"

Respond ONLY with a JSON object. No preamble, no markdown backticks.
{{
  "subject": "email subject line here",
  "body": "full email body here with newlines as \\n"
}}
"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw[raw.find("{"):raw.rfind("}") + 1]
        result = json.loads(cleaned)

    return {
        "subject": result.get("subject", ""),
        "body": result.get("body", ""),
        "email_to": contact_email
    }


def save_email_to_file(partner: dict, email: dict) -> str:
    """
    Saves each drafted email as a .txt file in output/emails/
    Named by company so they're easy to find and review.
    Returns the file path.
    """
    os.makedirs(OUTPUT_EMAILS_DIR, exist_ok=True)

    # Sanitize company name for use as filename
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in partner["name"])
    safe_name = safe_name.strip().replace(" ", "_")[:60]
    filename = f"{safe_name}.txt"
    filepath = os.path.join(OUTPUT_EMAILS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"TO: {email['email_to']}\n")
        f.write(f"SUBJECT: {email['subject']}\n")
        f.write(f"CLASSIFICATION: {partner.get('classification', '')}\n")
        f.write(f"COMPANY: {partner['name']}\n")
        f.write(f"WEBSITE: {partner.get('website', '')}\n")
        f.write("-" * 60 + "\n\n")
        f.write(email["body"])

    return filepath


def run_email_writer():
    """
    Reads classified CSV, drafts emails for all direct and general matches,
    saves each to output/emails/ and updates the CSV with email_drafted = yes.
    """
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        print(f"Classified file not found: {PARTNERS_CLASSIFIED_FILE}. Run classifier first.")
        return

    profile = load_profile()
    print(f"Profile loaded. Drafting emails...\n")

    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    # Add column if missing
    for p in partners:
        p.setdefault("email_drafted", "no")
        p.setdefault("email_file", "")

    total_drafted = 0
    skipped = 0

    for i, partner in enumerate(partners):
        classification = partner.get("classification", "")

        # Only write emails for matches
        if classification not in [MATCH_DIRECT, MATCH_GENERAL]:
            continue

        # Skip already drafted
        if partner.get("email_drafted") == "yes":
            skipped += 1
            continue

        print(f"[{i+1}/{len(partners)}] Drafting: {partner['name']} ({classification})")

        try:
            email = draft_email(partner, profile)
            filepath = save_email_to_file(partner, email)

            partner["email_drafted"] = "yes"
            partner["email_file"] = filepath
            total_drafted += 1

            print(f"    Subject: {email['subject']}")
            print(f"    Saved to: {filepath}")

        except Exception as e:
            print(f"    Error drafting for {partner['name']}: {e}")

        # Save progress every 20
        if total_drafted % 20 == 0 and total_drafted > 0:
            _save_progress(partners)
            print(f"  --- Progress saved ({total_drafted} drafted) ---\n")

        time.sleep(0.5)

    _save_progress(partners)

    print(f"\n--- Email Drafting Complete ---")
    print(f"Emails drafted: {total_drafted}")
    print(f"Skipped (already done): {skipped}")
    print(f"Emails saved to: {OUTPUT_EMAILS_DIR}")


def _save_progress(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    run_email_writer()
