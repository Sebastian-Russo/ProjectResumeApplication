# config.py — Central settings for the whole pipeline
# Think of this as the control panel: one place to tune everything,
# no magic numbers scattered across files.

import os
from dotenv import load_dotenv

load_dotenv()

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# --- Scraper ---
# The AWS partner search URL — we'll paginate through all 671 results
AWS_PARTNER_URL = "https://partners.amazonaws.com/search/partners/"
AWS_PARTNER_PARAMS = {
    "keyword": "Amazon Connect",
    "loc": "United States"
}

# How long to wait between requests so we don't hammer servers (in seconds)
SCRAPE_DELAY = 2
PAGE_TIMEOUT = 30000  # Playwright timeout in ms

# Keywords that signal a careers page link in a site's nav/footer
CAREER_PAGE_HINTS = [
    "careers", "jobs", "join us", "join our team",
    "work with us", "we're hiring", "open positions", "opportunities"
]

# Keywords to scan job listings for relevance to your background
JOB_KEYWORDS = [
    "amazon connect", "aws", "serverless", "lambda", "contact center",
    "cloud", "developer", "engineer", "backend", "python",
    "api gateway", "dynamodb", "step functions", "lex", "connect"
]

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
DATA_PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
OUTPUT_EMAILS_DIR = os.path.join(BASE_DIR, "output", "emails")
PROFILE_DIR = os.path.join(BASE_DIR, "profile")

# Output filenames
PARTNERS_RAW_FILE = os.path.join(DATA_RAW_DIR, "partners_raw.csv")
PARTNERS_CLASSIFIED_FILE = os.path.join(DATA_PROCESSED_DIR, "partners_classified.csv")
EMAILS_DRAFTED_FILE = os.path.join(DATA_PROCESSED_DIR, "emails_drafted.csv")

# --- Classification labels ---
MATCH_DIRECT = "direct_match"       # A specific relevant job posting found
MATCH_GENERAL = "general_match"     # No posting but company is relevant — cold outreach
MATCH_NONE = "no_match"             # Not relevant, skip

# --- Flask ---
FLASK_PORT = 5000
FLASK_DEBUG = True
