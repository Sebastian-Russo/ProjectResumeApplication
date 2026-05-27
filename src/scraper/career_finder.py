import csv
import time
import re
import os
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from config import (
    SCRAPE_DELAY, PAGE_TIMEOUT, CAREER_PAGE_HINTS,
    PARTNERS_RAW_FILE
)


def get_company_website(page, learn_more_url: str, company_name: str) -> str:
    """
    Visits the AWS partner detail page and finds the real company website.
    Looks for a link with text like "CloudHesive website".
    """
    try:
        page.goto(learn_more_url, wait_until="networkidle", timeout=PAGE_TIMEOUT)
        page.wait_for_timeout(2000)

        links = page.query_selector_all("a[href]")
        for link in links:
            href = link.get_attribute("href") or ""
            text = (link.inner_text() or "").strip().lower()

            if (
                "website" in text and
                href.startswith("http") and
                "amazonaws.com" not in href and
                "amazon.com" not in href
            ):
                return href.strip()

    except Exception as e:
        print(f"    Error getting website for {company_name}: {e}")

    return ""


def find_career_page(page, base_url: str) -> str:
    """
    Given a company homepage, finds their careers page URL.
    Tries common paths first, then scans nav/footer links.
    Returns the career page URL or empty string.
    """
    if not base_url or not base_url.startswith("http"):
        return ""

    # Common career URL patterns — try these directly first
    common_paths = [
        "/careers", "/jobs", "/about/careers", "/company/careers",
        "/about/jobs", "/join-us", "/work-with-us", "/join",
        "/careers/open-positions", "/about-us/careers", "/en/careers",
        "/we-are-hiring", "/hiring"
    ]

    for path in common_paths:
        candidate = urljoin(base_url, path)
        try:
            response = page.goto(candidate, wait_until="domcontentloaded", timeout=10000)
            if response and response.status == 200:
                page_text = page.inner_text("body").lower()
                if any(hint in page_text for hint in CAREER_PAGE_HINTS):
                    return candidate
        except Exception:
            continue

    # Fall back to scanning nav/footer links on the homepage
    try:
        page.goto(base_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        links = page.query_selector_all("a[href]")

        for link in links:
            try:
                href = link.get_attribute("href") or ""
                text = (link.inner_text() or "").lower().strip()

                if any(hint in text for hint in CAREER_PAGE_HINTS):
                    full_url = urljoin(base_url, href)
                    if is_same_domain(base_url, full_url):
                        return full_url
            except Exception:
                continue

    except PlaywrightTimeout:
        print(f"    Timeout on {base_url}")
    except Exception as e:
        print(f"    Error on {base_url}: {e}")

    return ""


def find_contact_email(page, base_url: str) -> str:
    """
    Looks for a contact/hiring email. Falls back to info@domain.com.
    """
    domain = urlparse(base_url).netloc.replace("www.", "")
    fallback = f"info@{domain}"
    email_pattern = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

    contact_paths = ["/contact", "/contact-us", "/about/contact", "/careers"]

    for path in contact_paths:
        try:
            page.goto(urljoin(base_url, path), wait_until="domcontentloaded", timeout=10000)
            emails = email_pattern.findall(page.inner_text("body"))

            for email in emails:
                el = email.lower()
                if any(w in el for w in ["career", "job", "hire", "recruit", "talent", "hr"]):
                    return email

            for email in emails:
                if "noreply" not in email.lower() and "no-reply" not in email.lower():
                    return email

        except Exception:
            continue

    return fallback


def is_same_domain(base_url: str, target_url: str) -> bool:
    base = urlparse(base_url).netloc.replace("www.", "")
    target = urlparse(target_url).netloc.replace("www.", "")
    return base == target or target == ""

def run_career_finder():
    if not os.path.exists(PARTNERS_RAW_FILE):
        print(f"No raw partners file found at {PARTNERS_RAW_FILE}. Run partner_scraper.py first.")
        return

    with open(PARTNERS_RAW_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    print(f"Processing {len(partners)} companies...\n")

    BATCH_SIZE = 50  # restart browser every 50 companies to prevent memory leak

    with sync_playwright() as p:
        browser = None
        page = None

        for i, partner in enumerate(partners):

            # Restart browser every BATCH_SIZE companies
            if i % BATCH_SIZE == 0:
                if browser:
                    browser.close()
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.set_default_timeout(PAGE_TIMEOUT)
                print(f"  --- Browser restarted at company {i+1} ---\n")

            # Skip already processed
            if partner.get("status") == "scraped":
                print(f"[{i+1}/{len(partners)}] Skipping {partner['name']} (already done)")
                continue

            print(f"[{i+1}/{len(partners)}] {partner['name']}")

            website = partner.get("website", "").strip()
            if not website:
                website = get_company_website(page, partner["learn_more_url"], partner["name"])
                partner["website"] = website

            if not website:
                print(f"    No website found — skipping")
                partner["status"] = "no_website"
                continue

            print(f"    Website: {website}")

            career_url = find_career_page(page, website)
            partner["career_page_url"] = career_url
            print(f"    Careers: {career_url or 'not found'}")

            contact_email = find_contact_email(page, website)
            partner["contact_email"] = contact_email
            print(f"    Email:   {contact_email}")

            partner["status"] = "scraped"

            if (i + 1) % 10 == 0:
                _save_progress(partners)
                print(f"  --- Progress saved ({i+1}/{len(partners)}) ---\n")

            time.sleep(SCRAPE_DELAY)

        if browser:
            browser.close()

    _save_progress(partners)
    print(f"\nDone.")

def _save_progress(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_RAW_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    run_career_finder()
