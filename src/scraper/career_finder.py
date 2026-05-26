# career_finder.py — Visits each company's website and hunts for their careers page
# Think of this like a postal worker who visits every house on the street:
# they knock on the front door (homepage), look for a sign that says "Jobs" or
# "Careers", then follow that sign to the right room. If there's no sign,
# they check the mailbox (footer) and the directory (sitemap).

import csv
import time
import re
import os
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from config import (
    SCRAPE_DELAY, PAGE_TIMEOUT, CAREER_PAGE_HINTS, JOB_KEYWORDS,
    PARTNERS_RAW_FILE, DATA_RAW_DIR
)


def find_career_page(page, base_url: str) -> tuple[str, list[str]]:
    """
    Given a company homepage, find their careers page and extract job listings.
    Returns: (career_page_url, [list of relevant job titles found])

    Strategy (in order):
    1. Check common career URL patterns directly
    2. Scan nav + footer links for career hints
    3. Give up gracefully
    """
    if not base_url or not base_url.startswith("http"):
        return "", []

    # --- Step 1: Try common URL patterns first (fast, no rendering needed) ---
    common_paths = [
        "/careers", "/jobs", "/about/careers", "/company/careers",
        "/about/jobs", "/join-us", "/work-with-us", "/careers/open-positions",
        "/about-us/careers", "/en/careers"
    ]

    for path in common_paths:
        candidate = urljoin(base_url, path)
        try:
            response = page.goto(candidate, wait_until="domcontentloaded", timeout=10000)
            if response and response.status == 200:
                # Make sure we actually landed on a careers-like page
                page_text = page.inner_text("body").lower()
                if any(hint in page_text for hint in CAREER_PAGE_HINTS):
                    jobs = extract_jobs_from_page(page)
                    return candidate, jobs
        except Exception:
            continue

    # --- Step 2: Load homepage and scan nav/footer links ---
    try:
        page.goto(base_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        links = page.query_selector_all("a[href]")

        for link in links:
            try:
                href = link.get_attribute("href") or ""
                text = (link.inner_text() or "").lower().strip()

                # Check if link text sounds like a careers page
                if any(hint in text for hint in CAREER_PAGE_HINTS):
                    full_url = urljoin(base_url, href)

                    # Stay on the same domain — don't follow off to LinkedIn etc.
                    if is_same_domain(base_url, full_url):
                        page.goto(full_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                        jobs = extract_jobs_from_page(page)
                        return full_url, jobs
            except Exception:
                continue

    except PlaywrightTimeout:
        print(f"    Timeout loading {base_url}")
    except Exception as e:
        print(f"    Error on {base_url}: {e}")

    return "", []


def extract_jobs_from_page(page) -> list[str]:
    """
    Scans a careers page for job listings relevant to our keywords.
    Returns a list of matching job title strings.

    Like a scanner at airport security — everything goes through,
    only flagged items (keyword matches) get pulled aside.
    """
    relevant_jobs = []

    try:
        # Grab all text that looks like job titles
        # Common patterns: <h2>, <h3>, <li>, elements with "job" or "position" in class
        title_selectors = [
            "h2", "h3", "h4",
            "[class*='job-title']", "[class*='position']",
            "[class*='role']", "[class*='opening']",
            "li a", ".job a", ".opening a"
        ]

        seen = set()
        for selector in title_selectors:
            elements = page.query_selector_all(selector)
            for el in elements:
                try:
                    text = el.inner_text().strip()
                    text_lower = text.lower()

                    # Only keep if it matches our keywords and isn't a duplicate
                    if (
                        text and
                        len(text) < 200 and          # Ignore paragraph-length text
                        text not in seen and
                        any(kw in text_lower for kw in JOB_KEYWORDS)
                    ):
                        relevant_jobs.append(text)
                        seen.add(text)
                except Exception:
                    continue

    except Exception as e:
        print(f"    Warning: job extraction error — {e}")

    return relevant_jobs[:20]  # Cap at 20 to keep CSV readable


def find_contact_email(page, base_url: str) -> str:
    """
    Looks for a contact/hiring email on the careers or contact page.
    Falls back to info@domain.com if nothing is found.
    """
    domain = urlparse(base_url).netloc.replace("www.", "")
    fallback = f"info@{domain}"

    email_pattern = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

    # Pages most likely to have a contact email
    contact_paths = ["/contact", "/contact-us", "/about/contact", "/careers"]

    for path in contact_paths:
        try:
            page.goto(urljoin(base_url, path), wait_until="domcontentloaded", timeout=10000)
            page_text = page.inner_text("body")
            emails = email_pattern.findall(page_text)

            # Prefer emails with hiring/careers/jobs in them
            for email in emails:
                el = email.lower()
                if any(word in el for word in ["career", "job", "hire", "recruit", "talent", "hr"]):
                    return email

            # Otherwise return first non-noreply email found
            for email in emails:
                if "noreply" not in email.lower() and "no-reply" not in email.lower():
                    return email

        except Exception:
            continue

    return fallback


def is_same_domain(base_url: str, target_url: str) -> bool:
    """Makes sure we don't accidentally follow links off to LinkedIn, Greenhouse, etc."""
    base_domain = urlparse(base_url).netloc.replace("www.", "")
    target_domain = urlparse(target_url).netloc.replace("www.", "")
    return base_domain == target_domain or target_domain == ""


def run_career_finder():
    """
    Reads partners_raw.csv, visits each company website,
    finds careers page + jobs + contact email, updates the CSV in place.
    """
    if not os.path.exists(PARTNERS_RAW_FILE):
        print(f"No raw partners file found at {PARTNERS_RAW_FILE}. Run partner_scraper.py first.")
        return

    # Load existing data
    with open(PARTNERS_RAW_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    print(f"Processing {len(partners)} companies...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        for i, partner in enumerate(partners):
            # Skip already processed rows (useful for resuming after a crash)
            if partner.get("career_page_url") or partner.get("status") == "scraped":
                print(f"[{i+1}/{len(partners)}] Skipping {partner['name']} (already done)")
                continue

            website = partner.get("website", "").strip()
            print(f"[{i+1}/{len(partners)}] {partner['name']} — {website}")

            if not website:
                partner["status"] = "no_website"
                continue

            career_url, jobs = find_career_page(page, website)
            contact_email = find_contact_email(page, website)

            partner["career_page_url"] = career_url
            partner["jobs_found"] = " | ".join(jobs) if jobs else ""
            partner["contact_email"] = contact_email
            partner["status"] = "scraped"

            print(f"    Career page: {career_url or 'not found'}")
            print(f"    Jobs matched: {len(jobs)}")
            print(f"    Contact: {contact_email}")

            # Save after every 10 companies in case of crash
            if (i + 1) % 10 == 0:
                _save_progress(partners)
                print(f"  --- Progress saved ({i+1}/{len(partners)}) ---\n")

            time.sleep(SCRAPE_DELAY)

        browser.close()

    _save_progress(partners)
    print(f"\nDone. Results saved to {PARTNERS_RAW_FILE}")


def _save_progress(partners: list[dict]) -> None:
    """Writes current state back to CSV — called periodically so crashes don't lose work."""
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_RAW_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    run_career_finder()

# Two things worth noting here:
# - the scraper saves progress every 10 companies
# so a crash at company 400 doesn't lose everything, and
# - it skips already-processed rows so you can safely resume.
