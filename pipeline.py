# pipeline.py — Runs the full pipeline end to end
# Think of this like an assembly line with 4 stations:
# Station 1 scrapes the partner directory → Station 2 finds career pages →
# Station 3 classifies with Claude → Station 4 drafts emails with Claude.
# You can run all stations or jump to any one individually.

import argparse
import sys
import os

# Make sure src modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scraper.partner_scraper import scrape_partner_directory, save_partners_to_csv
from src.scraper.career_finder import run_career_finder
from src.classifier.job_classifier import run_classifier
from src.writer.email_writer import run_email_writer


def run_phase_1():
    print("\n=== PHASE 1: Scraping AWS Partner Directory ===\n")
    partners = scrape_partner_directory()
    if partners:
        save_partners_to_csv(partners)
        print(f"\n✅ Phase 1 complete — {len(partners)} partners saved.")
    else:
        print("\n⚠️  Phase 1 returned no partners. Check your internet connection or selector patterns.")


def run_phase_2():
    print("\n=== PHASE 2: Finding Career Pages ===\n")
    run_career_finder()
    print("\n✅ Phase 2 complete.")


def run_phase_3():
    print("\n=== PHASE 3: AI Classification ===\n")
    run_classifier()
    print("\n✅ Phase 3 complete.")


def run_phase_4():
    print("\n=== PHASE 4: AI Email Drafting ===\n")
    run_email_writer()
    print("\n✅ Phase 4 complete.")


def run_all():
    run_phase_1()
    run_phase_2()
    run_phase_3()
    run_phase_4()
    print("\n🎉 Full pipeline complete. Run 'python app.py' to open the dashboard.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ProjectResumeApplication pipeline",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "--phase",
        type=str,
        default="all",
        choices=["1", "2", "3", "4", "all"],
        help=(
            "Which phase to run:\n"
            "  1   — Scrape AWS partner directory\n"
            "  2   — Find career pages + contact emails\n"
            "  3   — AI classify matches (requires profile/profile.txt)\n"
            "  4   — AI draft emails (requires phase 3 complete)\n"
            "  all — Run all phases in order (default)\n"
        )
    )

    args = parser.parse_args()

    phase_map = {
        "1": run_phase_1,
        "2": run_phase_2,
        "3": run_phase_3,
        "4": run_phase_4,
        "all": run_all
    }

    phase_map[args.phase]()
