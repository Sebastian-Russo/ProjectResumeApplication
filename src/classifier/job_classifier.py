import csv
import os
from config import (
    PARTNERS_RAW_FILE, PARTNERS_CLASSIFIED_FILE,
    DATA_PROCESSED_DIR,
    MATCH_HAS_CAREERS, MATCH_NO_CAREERS, MATCH_IGNORE,
    IGNORE_LIST
)


def is_ignored(name: str) -> bool:
    name_lower = name.lower()
    return any(ig.lower() in name_lower for ig in IGNORE_LIST)


def classify_company(partner: dict) -> dict:
    """
    Simple rule-based classification — no Claude needed here.
    has_careers: career page found
    no_careers: no career page
    ignore: on the ignore list
    """
    name = partner.get("name", "")

    if is_ignored(name):
        partner["classification"] = MATCH_IGNORE
        return partner

    if partner.get("career_page_url", "").strip():
        partner["classification"] = MATCH_HAS_CAREERS
    else:
        partner["classification"] = MATCH_NO_CAREERS

    return partner


def run_classifier():
    if not os.path.exists(PARTNERS_RAW_FILE):
        print(f"Raw file not found: {PARTNERS_RAW_FILE}")
        return

    with open(PARTNERS_RAW_FILE, "r", encoding="utf-8") as f:
        partners = list(csv.DictReader(f))

    for p in partners:
        p.setdefault("classification", "")
        p.setdefault("reasoning", "")
        p.setdefault("relevant_jobs", "")

    os.makedirs(DATA_PROCESSED_DIR, exist_ok=True)

    has_careers = no_careers = ignored = 0

    for partner in partners:
        classify_company(partner)
        label = partner["classification"]
        if label == MATCH_HAS_CAREERS:
            has_careers += 1
        elif label == MATCH_NO_CAREERS:
            no_careers += 1
        elif label == MATCH_IGNORE:
            ignored += 1

    _save_classified(partners)

    print(f"\n--- Classification Complete ---")
    print(f"Has careers page: {has_careers}")
    print(f"No careers page:  {no_careers}")
    print(f"Ignored:          {ignored}")
    print(f"Results saved to {PARTNERS_CLASSIFIED_FILE}")


def _save_classified(partners: list[dict]) -> None:
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


if __name__ == "__main__":
    run_classifier()
