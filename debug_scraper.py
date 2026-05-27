from playwright.sync_api import sync_playwright
import sys
sys.path.insert(0, '.')
from src.scraper.career_finder import get_company_website, find_career_page, find_contact_email

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    learn_more_url = "https://partners.amazonaws.com/partners/001E000000qK5f6IAC/CloudHesive"

    print("Step 1: Getting real website...")
    website = get_company_website(page, learn_more_url, "CloudHesive")
    print(f"  Website: {website}")

    print("Step 2: Finding careers page...")
    career_url = find_career_page(page, website)
    print(f"  Careers: {career_url or 'not found'}")

    print("Step 3: Finding contact email...")
    email = find_contact_email(page, website)
    print(f"  Email: {email}")

    browser.close()