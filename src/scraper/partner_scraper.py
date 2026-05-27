import csv
import time
import os
from playwright.sync_api import sync_playwright
from config import (
    AWS_PARTNER_URL, SCRAPE_DELAY, PAGE_TIMEOUT,
    PARTNERS_RAW_FILE, DATA_RAW_DIR
)


def scrape_partner_directory() -> list[dict]:
    partners = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        print("Loading AWS Partner Directory...")
        page.goto(
            f"{AWS_PARTNER_URL}?keyword=Amazon+Connect&loc=United+States",
            wait_until="networkidle"
        )

        page.wait_for_timeout(5000)
        page.wait_for_selector(".psf-partner-search-details-card__card", timeout=20000)

        page_num = 1
        total_pages = 68

        while True:
            print(f"  Scraping page {page_num}...")

            cards = page.query_selector_all(".psf-partner-search-details-card__card")
            print(f"    Found {len(cards)} cards on this page")

            for card in cards:
                try:
                    partner = extract_card_data(card)
                    if partner and partner.get("name"):
                        partners.append(partner)
                except Exception as e:
                    print(f"    Warning: couldn't parse a card — {e}")
                    continue

            # Save every 10 pages so a stop doesn't lose everything
            if page_num % 10 == 0:
                save_partners_to_csv(partners)
                print(f"  --- Progress saved ({len(partners)} partners so far) ---")

            if page_num >= total_pages:
                print(f"  Reached last page ({total_pages}). Done.")
                break

            next_btn = page.query_selector(".pagination-right-arrow button")
            if not next_btn:
                print(f"  No next button found. Done.")
                break

            next_btn.click()
            page_num += 1
            time.sleep(SCRAPE_DELAY)
            page.wait_for_selector(".psf-partner-search-details-card__card", timeout=15000)

        browser.close()

    print(f"\nFound {len(partners)} partners total.")
    return partners


def extract_card_data(card) -> dict:
    name = ""
    learn_more_url = ""

    el = card.query_selector(".psf-partner-search-details-card__title")
    if el:
        name = el.inner_text().strip()

    el = card.query_selector(".psf-partner-search-details-card__learnMore a")
    if el:
        href = el.get_attribute("href") or ""
        if href.startswith("/"):
            learn_more_url = f"https://partners.amazonaws.com{href}"
        else:
            learn_more_url = href

    return {
        "name": name,
        "learn_more_url": learn_more_url,
        "website": "",
        "career_page_url": "",
        "jobs_found": "",
        "contact_email": "",
        "classification": "",
        "email_drafted": "no",
        "status": "pending"
    }


def save_partners_to_csv(partners: list[dict]) -> None:
    os.makedirs(DATA_RAW_DIR, exist_ok=True)

    fieldnames = [
        "name", "learn_more_url", "website",
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
