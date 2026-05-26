# job_classifier.py — Uses Claude to classify each company as a match or not
# Think of this like a recruiting agency's intake desk:
# you hand them a stack of job postings, they read each one and sort them
# into three piles — "great fit", "maybe worth a shot", and "not for you".
# Claude is the recruiter. Your background is the brief they work from.

import csv
import json
import os
import time
from anthropic import Anthropic
from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    PARTNERS_RAW_FILE, PARTNERS_CLASSIFIED_FILE,
    DATA_PROCESSED_DIR, MATCH_DIRECT, MATCH_GENERAL, MATCH_NONE,
    PROFILE_DIR
)

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def load_profile() -> str:
    """
    Loads your resume/skills summary from profile/profile.txt.
    This is the context Claude uses to judge fit — the more specific, the better.
    """
    profile_path = os.path.join(PROFILE_DIR, "profile.txt")
    if not os.path.exists(profile_path):
        raise FileNotFoundError(
            f"No profile found at {profile_path}. "
            "Create profile/profile.txt with your background, skills, and target role."
        )
    with open(profile_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def classify_company(partner: dict, profile: str) -> dict:
    """
    Sends one company's data to Claude and gets back a classification + reasoning.
    Returns the partner dict enriched with classification fields.

    We ask Claude to respond in JSON so we can parse it reliably —
    like asking someone to fill out a form instead of writing a paragraph.
    """

    company_context = f"""
Company: {partner.get('name', 'Unknown')}
Website: {partner.get('website', 'N/A')}
Description: {partner.get('description', 'N/A')}
Career Page: {partner.get('career_page_url', 'Not found')}
Job Listings Found: {partner.get('jobs_found', 'None')}
Contact Email: {partner.get('contact_email', 'N/A')}
""".strip()

    prompt = f"""You are evaluating job opportunities for a candidate. Here is their background:

--- CANDIDATE PROFILE ---
{profile}
--- END PROFILE ---

Here is a company scraped from the AWS Partner Directory:

--- COMPANY DATA ---
{company_context}
--- END COMPANY DATA ---

Classify this opportunity and respond ONLY with a JSON object. No preamble, no markdown backticks.

Use this exact structure:
{{
  "classification": "direct_match" | "general_match" | "no_match",
  "reasoning": "1-2 sentence explanation",
  "relevant_jobs": ["job title 1", "job title 2"],
  "suggested_contact": "email address to use"
}}

Classification rules:
- "direct_match": One or more job listings closely match the candidate's skills (AWS, serverless, Amazon Connect, developer/engineer roles)
- "general_match": No specific listing found BUT the company works with Amazon Connect / AWS and cold outreach makes sense
- "no_match": Company is not relevant to the candidate's background or has no web presence worth pursuing

For suggested_contact: use the career/jobs email if found, otherwise use the contact_email field, otherwise construct info@domain.com from their website.
"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Claude occasionally adds a stray character — try to recover
        print(f"    Warning: JSON parse failed for {partner['name']}, attempting cleanup...")
        cleaned = raw[raw.find("{"):raw.rfind("}") + 1]
        result = json.loads(cleaned)

    # Write classification back into the partner record
    partner["classification"] = result.get("classification", MATCH_NONE)
    partner["reasoning"] = result.get("reasoning", "")
    partner["relevant_jobs"] = " | ".join(result.get("relevant_jobs", []))
    partner["contact_email"] = result.get("suggested_contact", partner.get("contact_email", ""))

    return partner


def run_classifier():
    """
    Reads the raw scraped CSV, classifies every company with Claude,
    writes results to data/processed/partners_classified.csv.
    Skips already-classified rows so you can resume safely.
    """
    if not os.path.exists(PARTNERS_RAW_FILE):
        print(f"Raw file not found: {PARTNERS_RAW_FILE}. Run the scraper first.")
        return

    profile = load_profile()
    print(f"Profile loaded ({len(profile)} chars)\n")

    with open(PARTNERS_RAW_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    # Add new columns if they don't exist yet
    for p in partners:
        p.setdefault("reasoning", "")
        p.setdefault("relevant_jobs", "")

    os.makedirs(DATA_PROCESSED_DIR, exist_ok=True)

    total = len(partners)
    direct = general = skipped = 0

    for i, partner in enumerate(partners):
        # Skip already classified
        if partner.get("classification") in [MATCH_DIRECT, MATCH_GENERAL, MATCH_NONE]:
            print(f"[{i+1}/{total}] Skipping {partner['name']} (already classified)")
            skipped += 1
            continue

        print(f"[{i+1}/{total}] Classifying: {partner['name']}...")

        try:
            partner = classify_company(partner, profile)
            label = partner["classification"]

            if label == MATCH_DIRECT:
                direct += 1
                print(f"    ✅ DIRECT MATCH — {partner['relevant_jobs']}")
            elif label == MATCH_GENERAL:
                general += 1
                print(f"    📬 GENERAL MATCH — {partner['reasoning'][:80]}")
            else:
                print(f"    ❌ No match")

        except Exception as e:
            print(f"    Error classifying {partner['name']}: {e}")
            partner["classification"] = "error"

        # Save progress every 20 companies
        if (i + 1) % 20 == 0:
            _save_classified(partners)
            print(f"  --- Progress saved ({i+1}/{total}) ---\n")

        # Be gentle with the API — small delay between calls
        time.sleep(0.5)

    _save_classified(partners)

    print(f"\n--- Classification Complete ---")
    print(f"Direct matches:  {direct}")
    print(f"General matches: {general}")
    print(f"No match:        {total - direct - general - skipped}")
    print(f"Skipped:         {skipped}")
    print(f"Results saved to {PARTNERS_CLASSIFIED_FILE}")


def _save_classified(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    run_classifier()
