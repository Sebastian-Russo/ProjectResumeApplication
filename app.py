import csv
import os
from flask import Flask, render_template, request, jsonify
from config import PARTNERS_CLASSIFIED_FILE, OUTPUT_EMAILS_DIR, FLASK_PORT, FLASK_DEBUG
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)


def load_partners() -> list[dict]:
    if not os.path.exists(PARTNERS_CLASSIFIED_FILE):
        return []
    with open(PARTNERS_CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_partners(partners: list[dict]) -> None:
    if not partners:
        return
    fieldnames = list(partners[0].keys())
    with open(PARTNERS_CLASSIFIED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partners)


def load_email_body(email_file: str) -> str:
    if not email_file or not os.path.exists(email_file):
        return ""
    with open(email_file, "r", encoding="utf-8") as f:
        return f.read()


def save_email_body(email_file: str, content: str) -> None:
    if not email_file:
        return
    with open(email_file, "w", encoding="utf-8") as f:
        f.write(content)


def get_stats(partners: list[dict]) -> dict:
    return {
        "total":        len(partners),
        "sent":         sum(1 for p in partners if p.get("status") == "sent"),
        "pending":      sum(1 for p in partners if p.get("status") in ["scraped", "pending"]),
        "needs_reply":  sum(1 for p in partners if p.get("status") == "needs_reply"),
        "positive":     sum(1 for p in partners if p.get("response_type") == "positive"),
        "negative":     sum(1 for p in partners if p.get("status") == "archived:rejected"),
        "bounced":      sum(1 for p in partners if p.get("status") in ["bounce:retry_queued", "archived:bad_email"]),
        "retry_queued": sum(1 for p in partners if p.get("status") == "bounce:retry_queued"),
        "ignored":      sum(1 for p in partners if p.get("classification") == "ignore"),
        "has_careers":  sum(1 for p in partners if p.get("classification") == "has_careers"),
        "no_careers":   sum(1 for p in partners if p.get("classification") == "no_careers"),
    }


@app.route("/")
def index():
    partners = load_partners()
    stats = get_stats(partners)
    filter_by = request.args.get("filter", "needs_reply")
    search = request.args.get("search", "").lower()

    if filter_by == "needs_reply":
        filtered = [p for p in partners if p.get("status") == "needs_reply"]
    elif filter_by == "sent":
        filtered = [p for p in partners if p.get("status") == "sent"]
    elif filter_by == "bounced":
        filtered = [p for p in partners if p.get("status") in ["bounce:retry_queued", "archived:bad_email"]]
    elif filter_by == "rejected":
        filtered = [p for p in partners if p.get("status") == "archived:rejected"]
    elif filter_by == "pending":
        filtered = [p for p in partners if p.get("status") in ["scraped", "pending"]]
    else:
        filtered = partners

    if search:
        filtered = [p for p in filtered if search in p.get("name", "").lower()]

    return render_template("index.html",
        partners=filtered,
        stats=stats,
        filter_by=filter_by,
        search=search,
        total_shown=len(filtered)
    )


@app.route("/company/<int:index>")
def company_detail(index):
    partners = load_partners()
    if index < 0 or index >= len(partners):
        return "Not found", 404
    partner = partners[index]
    email_content = load_email_body(partner.get("email_file", ""))
    return render_template("company.html", partner=partner, email_content=email_content, index=index)


@app.route("/api/update_status", methods=["POST"])
def update_status():
    data = request.json
    idx = data.get("index")
    new_status = data.get("status")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    from datetime import datetime
    now = datetime.now().isoformat()
    partners[idx]["status"] = new_status
    history = partners[idx].get("status_history", "")
    partners[idx]["status_history"] = f"{history}|{new_status}:{now}" if history else f"{new_status}:{now}"
    save_partners(partners)
    return jsonify({"success": True})


@app.route("/api/save_email", methods=["POST"])
def save_email():
    data = request.json
    idx = data.get("index")
    content = data.get("content", "")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    save_email_body(partners[idx].get("email_file", ""), content)
    return jsonify({"success": True})


@app.route("/api/scan", methods=["POST"])
def scan_inbox():
    try:
        from src.gmail.monitor import run_monitor
        stats = run_monitor()
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/send_reply", methods=["POST"])
def send_reply():
    data = request.json
    idx = data.get("index")
    body = data.get("body", "")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    partner = partners[idx]
    try:
        from src.gmail.gmail_client import get_gmail_service, send_email
        from datetime import datetime
        service = get_gmail_service()
        subject = f"Re: Amazon Connect Developer — Exploring Opportunities at {partner['name']}"
        send_email(service, partner.get("contact_email", ""), subject, body)
        now = datetime.now().isoformat()
        partners[idx]["status"] = "reply_sent"
        history = partners[idx].get("status_history", "")
        partners[idx]["status_history"] = f"{history}|reply_sent:{now}" if history else f"reply_sent:{now}"
        save_partners(partners)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/retry_bounced", methods=["POST"])
def retry_bounced():
    try:
        from src.gmail.monitor import send_fallback_emails
        send_fallback_emails()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stats")
def api_stats():
    partners = load_partners()
    return jsonify(get_stats(partners))


if __name__ == "__main__":
    app.run(port=FLASK_PORT, debug=FLASK_DEBUG)