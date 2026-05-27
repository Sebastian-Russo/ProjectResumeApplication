import csv
import json
import os
import time
from anthropic import Anthropic
from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    PARTNERS_CLASSIFIED_FILE,
    OUTPUT_EMAILS_DIR,
    MATCH_HAS_CAREERS, MATCH_NO_CAREERS, MATCH_IGNORE
)

client = Anthropic(api_key=ANTHROPIC_API_KEY)

RESUME_SUMMARY = """
Name: Sebastian Russo
Title: AWS Cloud Developer — Amazon Connect & AWS Serverless
Location: Bethlehem, PA
Email: russo.sebastian@gmail.com

4+ years specialized experience building Amazon Connect contact center solutions
and serverless AWS architectures. Deep expertise in Lex V2 bot design, Lambda
integrations, CDK infrastructure, and end-to-end IVR development. Delivered
high-volume enterprise call center systems for government (SSA) and commercial
clients (Amazon ProServe satellite/telecom). Currently expanding into agentic AI
using Bedrock, Claude, and multi-agent orchestration.

Key skills: Amazon Connect, Lambda, Lex V2, API Gateway, DynamoDB, CDK,
CloudFormation, Step Functions, Kinesis, QuickSight, CloudWatch, Python,
JavaScript/TypeScript, ReactJS. Public Trust clearance. 4x AWS certified.
"""

BODY_TEMPLATE = """I came across {company_name} in the AWS Partner directory and wanted to reach out directly about potential opportunities on your AWS Connect team.

I'm an AWS Cloud Developer with over 4 years of specialized experience building and implementing Amazon Connect contact center solutions. My expertise spans serverless architectures, conversational patterns with Lex V2, and full-stack integrations using Lambda, DynamoDB, S3, Athena, and QuickSight. I've delivered high-volume contact center systems for clients including the Social Security Administration and an Amazon ProServe satellite/telecom engagement — both involving complex IVR flows, self-service bots, and real-time monitoring pipelines.

{personalized_line}

My resume is attached. I'd welcome the chance to connect with your hiring manager or technical lead — even if there isn't a current opening, I'm happy to be kept in mind for future needs.

Best,
Sebastian Russo
russo.sebastian@gmail.com
484-326-9897
linkedin.com/in/sebastian-russo-2054565a"""


def draft_email(partner: dict) -> dict:
    """
    Uses Claude to generate one personalized sentence about the company,
    then slots it into the body template.
    Returns dict with subject, body, email_to.
    """
    company_name = partner.get("name", "your company")
    contact_email = partner.get("contact_email", "")
    description = partner.get("description", "")
    career_page_url = partner.get("career_page_url", "")
    classification = partner.get("classification", "")

    # Ask Claude for just one personalized sentence
    context = f"Company: {company_name}\nDescription: {description}\nCareer page: {career_page_url}"

    prompt = f"""Write exactly one sentence (20-35 words) personalizing an outreach email to this AWS partner company.
The sentence should reference something specific about what they do with AWS/Amazon Connect if possible,
or simply note that their work aligns with the candidate's background.
Do not start with "I" and do not use generic phrases like "I was impressed by".
Just output the single sentence, nothing else.

{context}"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        personalized_line = response.content[0].text.strip()
    except Exception:
        personalized_line = f"Your work as an AWS Connect partner aligns closely with my background."

    body = BODY_TEMPLATE.format(
        company_name=company_name,
        personalized_line=personalized_line
    )

    subject = f"Amazon Connect Developer — Exploring Opportunities at {company_name}"

    return {
        "subject": subject,
        "body": body,
        "email_to": contact_email,
        "personalized_line": personalized_line
    }


def save_email_to_file(partner: dict, email: dict) -> str:
    os.makedirs(OUTPUT_EMAILS_DIR, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in partner["name"])
    safe_name = safe_name.strip().replace(" ", "_")[:60]
    filepath = os.path.join(OUTPUT_EMAILS_DIR, f"{safe_name}.txt")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"TO: {email['email_to']}\n")
        f.write(f"SUBJECT: {email['subject']}\n")
        f.write(f"COMPANY: {partner['name']}\n")
        f.write(f"CLASSIFICATION: {partner.get('classification', '')}\n")
        f.write("-" * 60 + "\n\n")
        f.write(email["body"])

    return filepath


def run_email_writer():
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        print(f"Classified file not found. Run classifier first.")
        return

    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    for p in partners:
        p.setdefault("email_drafted", "no")
        p.setdefault("email_file", "")

    total = skipped = errors = 0

    for i, partner in enumerate(partners):
        classification = partner.get("classification", "")

        if classification == MATCH_IGNORE:
            continue

        if classification not in [MATCH_HAS_CAREERS, MATCH_NO_CAREERS]:
            continue

        if partner.get("email_drafted") == "yes":
            skipped += 1
            continue

        print(f"[{i+1}/{len(partners)}] Drafting: {partner['name']}")

        try:
            email = draft_email(partner)
            filepath = save_email_to_file(partner, email)
            partner["email_drafted"] = "yes"
            partner["email_file"] = filepath
            total += 1
            print(f"    {email['personalized_line'][:80]}")

        except Exception as e:
            print(f"    Error: {e}")
            errors += 1

        if total % 20 == 0 and total > 0:
            _save_progress(partners)
            print(f"  --- Progress saved ({total} drafted) ---\n")

        time.sleep(0.3)

    _save_progress(partners)

    print(f"\n--- Email Drafting Complete ---")
    print(f"Drafted:  {total}")
    print(f"Skipped:  {skipped}")
    print(f"Errors:   {errors}")
    print(f"Saved to: {OUTPUT_EMAILS_DIR}")


def _save_progress(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    run_email_writer()
