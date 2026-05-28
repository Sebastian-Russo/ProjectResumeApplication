# pipeline.py — Runs the full pipeline end to end
# Think of this like an assembly line with 4 stations:
# Station 1 scrapes the partner directory → Station 2 finds career pages →
# Station 3 classifies with Claude → Station 4 drafts emails with Claude.
# You can run all stations or jump to any one individually.
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scraper.partner_scraper import scrape_partner_directory, save_partners_to_csv
from src.scraper.career_finder import run_career_finder
from src.classifier.job_classifier import run_classifier
from src.writer.email_writer import run_email_writer
from src.gmail.sender import run_sender
from src.gmail.monitor import run_monitor, send_fallback_emails


def run_phase_1():
    print("\n=== PHASE 1: Scraping AWS Partner Directory ===\n")
    partners = scrape_partner_directory()
    if partners:
        save_partners_to_csv(partners)
        print(f"\n✅ Phase 1 complete — {len(partners)} partners saved.")
    else:
        print("\n⚠️  Phase 1 returned no partners.")


def run_phase_2():
    print("\n=== PHASE 2: Finding Career Pages ===\n")
    run_career_finder()
    print("\n✅ Phase 2 complete.")


def run_phase_3():
    print("\n=== PHASE 3: Classification ===\n")
    run_classifier()
    print("\n✅ Phase 3 complete.")


def run_phase_4():
    print("\n=== PHASE 4: AI Email Drafting ===\n")
    run_email_writer()
    print("\n✅ Phase 4 complete.")


def run_phase_5a():
    print("\n=== PHASE 5a: Send Email Blast ===\n")
    run_sender()
    print("\n✅ Phase 5a complete.")


def run_phase_5b():
    print("\n=== PHASE 5b: Scan Inbox for Replies ===\n")
    run_monitor()
    print("\n✅ Phase 5b complete.")


def run_phase_5c():
    print("\n=== PHASE 5c: Retry Bounced Emails ===\n")
    send_fallback_emails()
    print("\n✅ Phase 5c complete.")


def run_all():
    run_phase_1()
    run_phase_2()
    run_phase_3()
    run_phase_4()
    run_phase_5a()
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
        choices=["1", "2", "3", "4", "5a", "5b", "5c", "all"],
        help=(
            "Which phase to run:\n"
            "  1   — Scrape AWS partner directory\n"
            "  2   — Find career pages + contact emails\n"
            "  3   — Classify companies\n"
            "  4   — AI draft emails\n"
            "  5a  — Send email blast\n"
            "  5b  — Scan inbox for replies\n"
            "  5c  — Retry bounced emails\n"
            "  all — Run phases 1-5a in order (default)\n"
        )
    )

    args = parser.parse_args()

    phase_map = {
        "1":   run_phase_1,
        "2":   run_phase_2,
        "3":   run_phase_3,
        "4":   run_phase_4,
        "5a":  run_phase_5a,
        "5b":  run_phase_5b,
        "5c":  run_phase_5c,
        "all": run_all
    }

    phase_map[args.phase]()
