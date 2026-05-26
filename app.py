# app.py — Flask dashboard to review drafted emails and track application status
# Think of this like a triage desk: all your drafted emails land in one inbox,
# you read each one, edit if needed, mark it sent, and track where things stand.
# Nothing gets sent automatically — you stay in full control.

import csv
import os
from flask import Flask, render_template, request, jsonify
from config import (
    PARTNERS_CLASSIFIED_FILE, OUTPUT_EMAILS_DIR,
    FLASK_PORT, FLASK_DEBUG,
    MATCH_DIRECT, MATCH_GENERAL
)

app = Flask(__name__)


def load_partners() -> list[dict]:
    """Load all partners from the classified CSV."""
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        return []
    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_partners(partners: list[dict]) -> None:
    """Write partners back to CSV after status updates."""
    if not partners:
        return
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


def load_email_body(email_file: str) -> str:
    """Read the drafted email text from disk."""
    if not email_file or not os.path.exists(email_file):
        return ""
    with open(email_file, "r", encoding="utf-8") as f:
        return f.read()


def save_email_body(email_file: str, content: str) -> None:
    """Save edited email text back to disk."""
    if not email_file:
        return
    with open(email_file, "w", encoding="utf-8") as f:
        f.write(content)


# --- Routes ---

@app.route("/")
def index():
    """Main dashboard — summary stats + filterable company list."""
    partners = load_partners()

    # Stats for the top bar
    stats = {
        "total": len(partners),
        "direct": sum(1 for p in partners if p.get("classification") == MATCH_DIRECT),
        "general": sum(1 for p in partners if p.get("classification") == MATCH_GENERAL),
        "emails_drafted": sum(1 for p in partners if p.get("email_drafted") == "yes"),
        "applied": sum(1 for p in partners if p.get("status") == "applied"),
        "responded": sum(1 for p in partners if p.get("status") == "responded"),
        "interviewing": sum(1 for p in partners if p.get("status") == "interviewing"),
    }

    # Filter by classification or status from query param
    filter_by = request.args.get("filter", "all")
    if filter_by == "direct":
        partners = [p for p in partners if p.get("classification") == MATCH_DIRECT]
    elif filter_by == "general":
        partners = [p for p in partners if p.get("classification") == MATCH_GENERAL]
    elif filter_by == "applied":
        partners = [p for p in partners if p.get("status") == "applied"]
    elif filter_by == "pending":
        partners = [p for p in partners if p.get("status") not in ["applied", "responded", "interviewing", "rejected"]]
    elif filter_by == "responded":
        partners = [p for p in partners if p.get("status") == "responded"]
    elif filter_by == "interviewing":
        partners = [p for p in partners if p.get("status") == "interviewing"]

    return render_template("index.html", partners=partners, stats=stats, filter_by=filter_by)


@app.route("/company/<int:index>")
def company_detail(index):
    """Detail view for a single company — shows email, allows editing."""
    partners = load_partners()
    if index < 0 or index >= len(partners):
        return "Not found", 404

    partner = partners[index]
    email_content = load_email_body(partner.get("email_file", ""))

    return render_template(
        "company.html",
        partner=partner,
        email_content=email_content,
        index=index
    )


@app.route("/api/update_status", methods=["POST"])
def update_status():
    """API endpoint to update a company's application status."""
    data = request.json
    idx = data.get("index")
    new_status = data.get("status")

    valid_statuses = ["pending", "applied", "responded", "interviewing", "rejected", "not_relevant"]
    if new_status not in valid_statuses:
        return jsonify({"error": "Invalid status"}), 400

    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400

    partners[idx]["status"] = new_status
    save_partners(partners)

    return jsonify({"success": True, "name": partners[idx]["name"], "status": new_status})


@app.route("/api/save_email", methods=["POST"])
def save_email():
    """API endpoint to save edits made to a drafted email."""
    data = request.json
    idx = data.get("index")
    content = data.get("content", "")

    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400

    email_file = partners[idx].get("email_file", "")
    save_email_body(email_file, content)

    return jsonify({"success": True})


@app.route("/api/stats")
def api_stats():
    """Returns current stats as JSON — for refreshing the dashboard header."""
    partners = load_partners()
    return jsonify({
        "total": len(partners),
        "direct": sum(1 for p in partners if p.get("classification") == MATCH_DIRECT),
        "general": sum(1 for p in partners if p.get("classification") == MATCH_GENERAL),
        "emails_drafted": sum(1 for p in partners if p.get("email_drafted") == "yes"),
        "applied": sum(1 for p in partners if p.get("status") == "applied"),
        "responded": sum(1 for p in partners if p.get("status") == "responded"),
        "interviewing": sum(1 for p in partners if p.get("status") == "interviewing"),
    })


if __name__ == "__main__":
    app.run(port=FLASK_PORT, debug=FLASK_DEBUG)
