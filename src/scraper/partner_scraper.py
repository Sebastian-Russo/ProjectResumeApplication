# partner_scraper.py — Pulls all AWS Connect partners from the directory
# Think of this like a librarian going through a card catalog:
# we flip through every page of results, writing down each company's
# name and website before moving to the next page.

import csv
import time
import os
from playwright.sync_api import sync_playwright
from config import (
    AWS_PARTNER_URL, SCRAPE_DELAY, PAGE_TIMEOUT,
    PARTNERS_RAW_FILE, DATA_RAW_DIR
)


def scrape_partner_directory() -> list[dict]:
    """
    Navigates the AWS partner search, scrolls/paginates through all results,
    and extracts company name + website for each partner.
    Returns a list of dicts: [{name, website, location, description}, ...]
    """
    partners = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        print("Loading AWS Partner Directory...")
        page.goto(
            f"{AWS_PARTNER_URL}?keyword=Amazon+Connect&loc=United+States",
            wait_until="networkidle"
        )

        # The directory is a React SPA — we need to wait for cards to render
        page.wait_for_selector("[class*='PartnerCard'], [class*='partner-card'], .awsui-cards-card", timeout=15000)

        page_num = 1

        while True:
            print(f"  Scraping page {page_num}...")

            # Grab all partner cards currently visible
            cards = page.query_selector_all("[class*='PartnerCard'], [class*='partner-card']")

            if not cards:
                # Fallback: try generic card selectors
                cards = page.query_selector_all("li[class*='card'], div[class*='result']")

            for card in cards:
                try:
                    partner = extract_card_data(card)
                    if partner and partner.get("name"):
                        partners.append(partner)
                except Exception as e:
                    print(f"    Warning: couldn't parse a card — {e}")
                    continue

            # Check for a "Next" pagination button
            next_btn = page.query_selector("button[aria-label='Next page'], [class*='pagination'] button:last-child")

            if next_btn and next_btn.is_enabled():
                next_btn.click()
                time.sleep(SCRAPE_DELAY)
                page.wait_for_load_state("networkidle")
                page_num += 1
            else:
                print(f"  No more pages. Done at page {page_num}.")
                break

        browser.close()

    print(f"Found {len(partners)} partners total.")
    return partners


def extract_card_data(card) -> dict:
    """
    Pulls structured data out of a single partner card element.
    We try multiple selector patterns because AWS's React classes
    can be minified/hashed — defensive parsing is key here.
    """
    name = ""
    website = ""
    description = ""
    location = ""

    # Try to get company name
    for selector in ["h3", "h2", "[class*='name']", "[class*='title']", "strong"]:
        el = card.query_selector(selector)
        if el:
            name = el.inner_text().strip()
            if name:
                break

    # Try to get website URL from any anchor tag on the card
    for selector in ["a[href*='http']", "a[class*='website']", "a[class*='url']"]:
        el = card.query_selector(selector)
        if el:
            href = el.get_attribute("href") or ""
            # Filter out AWS's own internal links
            if href and "amazonaws.com" not in href and "amazon.com" not in href:
                website = href.strip()
                break

    # Try to get description text
    for selector in ["p", "[class*='description']", "[class*='summary']"]:
        el = card.query_selector(selector)
        if el:
            description = el.inner_text().strip()[:300]  # Cap at 300 chars
            if description:
                break

    # Try location
    for selector in ["[class*='location']", "[class*='city']", "[class*='region']"]:
        el = card.query_selector(selector)
        if el:
            location = el.inner_text().strip()
            if location:
                break

    return {
        "name": name,
        "website": website,
        "location": location,
        "description": description,
        "career_page_url": "",      # filled in next step
        "jobs_found": "",           # filled in next step
        "contact_email": "",        # filled in next step
        "classification": "",       # filled by classifier
        "email_drafted": "no",
        "status": "pending"
    }


def save_partners_to_csv(partners: list[dict]) -> None:
    """Saves the raw partner list to CSV so we don't have to re-scrape."""
    os.makedirs(DATA_RAW_DIR, exist_ok=True)

    fieldnames = [
        "name", "website", "location", "description",
        "career_page_url", "jobs_found", "contact_email",
        "classification", "email_drafted", "status"
    ]

    with open(PARTNERS_RAW_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)

    print(f"Saved {len(partners)} partners to {PARTNERS_RAW_FILE}")


if __name__ == "__main__":
    partners = scrape_partner_directory()
    save_partners_to_csv(partners)
