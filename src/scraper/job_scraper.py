# job_scraper.py — Reads career pages and extracts job listings
# Fast path: plain HTTP request + BeautifulSoup
# Slow path: Playwright for JS-rendered pages

import csv
import time
import os
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from config import (
    PARTNERS_RAW_FILE, SCRAPE_DELAY, PAGE_TIMEOUT, JOB_KEYWORDS
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ATS platforms that need Playwright (JS-rendered)
JS_PLATFORMS = ["greenhouse.io", "lever.co", "workday.com", "icims.com", "myworkdayjobs.com", "jobvite.com", "smartrecruiters.com"]


def is_js_platform(url: str) -> bool:
    return any(p in url for p in JS_PLATFORMS)


def fetch_with_requests(url: str) -> str:
    """Fast plain HTTP fetch. Returns page text or empty string."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            # Remove nav, footer, scripts, styles — keep main content
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)
    except Exception:
        pass
    return ""


def fetch_with_playwright(page, url: str) -> str:
    """Playwright fetch for JS-rendered pages."""
    try:
        page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT)
        page.wait_for_timeout(2000)
        return page.inner_text("body")
    except Exception:
        pass
    return ""


def extract_job_titles(text: str) -> list[str]:
    """
    Pulls lines from page text that look like job titles.
    Filters by keyword relevance and reasonable length.
    """
    jobs = []
    seen = set()

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for line in lines:
        line_lower = line.lower()

        # Must contain a job keyword
        if not any(kw in line_lower for kw in JOB_KEYWORDS):
            continue

        # Reasonable title length
        if len(line) < 5 or len(line) > 120:
            continue

        # Skip lines that are clearly not titles
        skip_phrases = ["cookie", "privacy", "copyright", "all rights", "subscribe", "newsletter", "follow us"]
        if any(p in line_lower for p in skip_phrases):
            continue

        if line not in seen:
            seen.add(line)
            jobs.append(line)

        if len(jobs) >= 15:
            break

    return jobs


def run_job_scraper():
    if not os.path.exists(PARTNERS_RAW_FILE):
        print(f"File not found: {PARTNERS_RAW_FILE}")
        return

    with open(PARTNERS_RAW_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    # Only process companies that have a career page and no jobs yet
    to_process = [
        p for p in partners
        if p.get("career_page_url") and not p.get("jobs_found")
    ]

    print(f"Scraping job listings for {len(to_process)} companies with career pages...\n")

    with sync_playwright() as p:
        browser = None
        page = None

        for i, partner in enumerate(partners):
            career_url = partner.get("career_page_url", "").strip()

            if not career_url:
                continue

            if partner.get("jobs_found"):
                print(f"[{i+1}/{len(partners)}] Skipping {partner['name']} (already done)")
                continue

            print(f"[{i+1}/{len(partners)}] {partner['name']} — {career_url}")

            # Try fast path first
            if not is_js_platform(career_url):
                text = fetch_with_requests(career_url)

                # If we got very little text, probably JS-rendered — fall back
                if len(text) < 200:
                    text = ""

            else:
                text = ""

            # Slow path if needed
            if not text:
                if not browser:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(user_agent=HEADERS["User-Agent"])
                    page = context.new_page()
                    page.set_default_timeout(PAGE_TIMEOUT)

                print(f"    JS render needed...")
                text = fetch_with_playwright(page, career_url)

            # Extract job titles
            jobs = extract_job_titles(text)
            partner["jobs_found"] = " | ".join(jobs) if jobs else ""

            if jobs:
                print(f"    Found {len(jobs)} relevant listings")
                for j in jobs[:3]:
                    print(f"      - {j}")
            else:
                print(f"    No relevant listings found")

            # Restart browser every 50 to prevent memory leak
            if browser and (i + 1) % 50 == 0:
                browser.close()
                browser = None
                page = None

            # Save every 20
            if (i + 1) % 20 == 0:
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
    run_job_scraper()
