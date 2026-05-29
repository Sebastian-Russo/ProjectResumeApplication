import csv
import os
import json
import io
from datetime import datetime, timedelta
from flask import Flask, redirect, request, jsonify, send_file
from flask_cors import CORS
from config import PARTNERS_CLASSIFIED_FILE, FLASK_PORT, FLASK_DEBUG
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)  # Allow React dev server on port 3000


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
    if not email_file:
        return ""
    # Try absolute path first
    if os.path.exists(email_file):
        with open(email_file, "r", encoding="utf-8") as f:
            return f.read()
    # Try relative to project root
    base = os.path.dirname(os.path.abspath(__file__))
    rel_path = os.path.join(base, email_file)
    if os.path.exists(rel_path):
        with open(rel_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def save_email_body(email_file: str, content: str) -> None:
    if not email_file:
        return
    with open(email_file, "w", encoding="utf-8") as f:
        f.write(content)


def get_stats(partners: list[dict]) -> dict:
    now = datetime.now()
    total         = len(partners)
    sent          = sum(1 for p in partners if p.get("status") == "sent")
    pending       = sum(1 for p in partners if p.get("status") in ["scraped", "pending"] and p.get("classification") != "ignore")
    ignored       = sum(1 for p in partners if p.get("classification") == "ignore")
    meeting_req   = sum(1 for p in partners if p.get("status") == "meeting_requested")
    meeting_sched = sum(1 for p in partners if p.get("status") == "meeting_scheduled")
    meeting_done  = sum(1 for p in partners if p.get("status") == "meeting_completed")
    apply_link    = sum(1 for p in partners if p.get("status") == "apply_link_received")
    needs_reply   = sum(1 for p in partners if p.get("status") == "needs_reply")
    reply_sent    = sum(1 for p in partners if p.get("status") == "reply_sent")
    keep_warm     = sum(1 for p in partners if p.get("status") == "keep_warm")
    offer         = sum(1 for p in partners if p.get("status") == "offer_received")
    rejected      = sum(1 for p in partners if p.get("status") == "archived:rejected")
    bad_email     = sum(1 for p in partners if p.get("status") == "archived:bad_email")
    no_response   = sum(1 for p in partners if p.get("status") == "archived:no_response")
    bounced       = sum(1 for p in partners if p.get("status") in ["bounce:retry_queued", "archived:bad_email"])
    retry_queued  = sum(1 for p in partners if p.get("status") == "bounce:retry_queued")
    thankyou_due  = sum(1 for p in partners if p.get("response_type") == "negative_no_fit" and not p.get("thankyou_sent"))
    keepwarm_due  = sum(1 for p in partners if p.get("response_type") == "negative_no_opening" and not p.get("keepwarm_sent"))

    next_actions = {}
    for p in partners:
        na = p.get("next_action", "")
        if na and na != "none":
            next_actions[na] = next_actions.get(na, 0) + 1

    meeting_outcomes = {}
    for p in partners:
        notes = p.get("meeting_notes", "")
        if notes:
            for outcome in ["scheduled", "completed", "offer", "pass"]:
                if outcome in notes.lower():
                    meeting_outcomes[outcome] = meeting_outcomes.get(outcome, 0) + 1

    retry_1st = sum(1 for p in partners if p.get("status_history", "").count("sent_fallback") == 1)
    retry_2nd = sum(1 for p in partners if p.get("status_history", "").count("sent_fallback") == 2)
    retry_3rd = sum(1 for p in partners if p.get("status_history", "").count("sent_fallback") >= 3)

    total_sent = sum(1 for p in partners if p.get("sent_at"))
    total_replied = sum(1 for p in partners if p.get("last_reply"))
    response_rate = round((total_replied / total_sent * 100), 1) if total_sent > 0 else 0

    days_list = [int(p["response_rate_days"]) for p in partners
                 if p.get("response_rate_days") and p["response_rate_days"].isdigit()]
    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else 0

    due_today = []
    for p in partners:
        date_str = p.get("next_action_date", "")
        if date_str:
            try:
                if datetime.strptime(date_str, "%Y-%m-%d").date() <= now.date():
                    due_today.append(p.get("name", ""))
            except Exception:
                pass

    all_tags = set()
    for p in partners:
        for t in (p.get("tags", "") or "").split("|"):
            t = t.strip()
            if t:
                all_tags.add(t)

    return {
        "total": total, "sent": sent, "pending": pending, "ignored": ignored,
        "meeting_requested": meeting_req, "meeting_scheduled": meeting_sched,
        "meeting_completed": meeting_done, "apply_link_received": apply_link,
        "needs_reply": needs_reply, "reply_sent": reply_sent,
        "keep_warm": keep_warm, "offer_received": offer,
        "rejected": rejected, "bad_email": bad_email, "no_response": no_response,
        "bounced": bounced, "retry_queued": retry_queued,
        "thankyou_due": thankyou_due, "keepwarm_due": keepwarm_due,
        "next_actions": next_actions, "meeting_outcomes": meeting_outcomes,
        "retry_1st": retry_1st, "retry_2nd": retry_2nd, "retry_3rd": retry_3rd,
        "response_rate": response_rate, "avg_days_to_response": avg_days,
        "due_today": due_today, "all_tags": sorted(all_tags),
    }


def _is_due(date_str: str) -> bool:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() <= datetime.now().date()
    except Exception:
        return False


def serialize_partner(p: dict, index: int) -> dict:
    """Adds index and parses JSON fields for API responses."""
    result = dict(p)
    result["index"] = index
    try:
        result["contacts"] = json.loads(p.get("contacts", "[]") or "[]")
    except Exception:
        result["contacts"] = []
    result["tags"] = [t.strip() for t in (p.get("tags", "") or "").split("|") if t.strip()]
    return result


# --- Routes ---

@app.route("/")
def root():
    """Flask is API-only; the React UI runs on the Vite dev server."""
    if FLASK_DEBUG:
        return redirect("http://localhost:5173")
    return (
        "<p>API server running. Build the frontend with "
        "<code>cd frontend && npm run build</code> and serve the <code>dist/</code> folder.</p>",
        200,
        {"Content-Type": "text/html"},
    )


@app.route("/api/partners")
def get_partners():
    partners = load_partners()
    filter_by = request.args.get("filter", "all")
    search = request.args.get("search", "").lower()
    tag_filter = request.args.get("tag", "").lower()

    filter_map = {
        "action":    lambda p: p.get("status") in ["meeting_requested", "apply_link_received", "needs_reply"],
        "meeting":   lambda p: p.get("status") in ["meeting_requested", "meeting_scheduled", "meeting_completed"],
        "apply":         lambda p: p.get("status") == "apply_link_received",
        "needs_reply":   lambda p: p.get("status") == "needs_reply",
        "offer_received": lambda p: p.get("status") == "offer_received",
        "keep_warm":     lambda p: p.get("status") == "keep_warm",
        "sent":      lambda p: p.get("status") == "sent",
        "bounced":   lambda p: p.get("status") in ["bounce:retry_queued", "archived:bad_email"],
        "rejected":  lambda p: p.get("status") == "archived:rejected",
        "pending":   lambda p: p.get("status") in ["scraped", "pending"] and p.get("classification") != "ignore",
        "ignored":   lambda p: p.get("classification") == "ignore",
        "archived":  lambda p: "archived" in p.get("status", ""),
        "due_today": lambda p: bool(p.get("next_action_date")) and _is_due(p.get("next_action_date", "")),
        "all":       lambda p: True,
    }

    fn = filter_map.get(filter_by, filter_map["all"])
    filtered = [(i, p) for i, p in enumerate(partners) if fn(p)]

    if search:
        filtered = [(i, p) for i, p in filtered if search in p.get("name", "").lower()]

    if tag_filter:
        filtered = [(i, p) for i, p in filtered if tag_filter in (p.get("tags", "") or "").lower()]

    return jsonify([serialize_partner(p, i) for i, p in filtered])


@app.route("/api/partners/<int:index>")
def get_partner(index):
    partners = load_partners()
    if index < 0 or index >= len(partners):
        return jsonify({"error": "Not found"}), 404
    partner = serialize_partner(partners[index], index)
    partner["email_content"] = load_email_body(partners[index].get("email_file", ""))
    return jsonify(partner)


@app.route("/api/stats")
def api_stats():
    partners = load_partners()
    return jsonify(get_stats(partners))


@app.route("/api/activity")
def api_activity():
    from src.gmail.monitor import get_activity_log
    return jsonify(get_activity_log(20))


@app.route("/api/partners/<int:index>", methods=["PATCH"])
def update_partner(index):
    partners = load_partners()
    if index < 0 or index >= len(partners):
        return jsonify({"error": "Not found"}), 404

    data = request.json
    now = datetime.now().isoformat()

    # Status update
    if "status" in data:
        new_status = data["status"]
        partners[index]["status"] = new_status
        history = partners[index].get("status_history", "")
        partners[index]["status_history"] = f"{history}|{new_status}:{now}" if history else f"{new_status}:{now}"

    # Next action
    if "next_action" in data:
        partners[index]["next_action"] = data["next_action"]
    if "next_action_date" in data:
        partners[index]["next_action_date"] = data["next_action_date"]

    # Meeting notes + outcome
    if "meeting_notes" in data:
        partners[index]["meeting_notes"] = data["meeting_notes"]
    if "meeting_outcome" in data:
        outcome = data["meeting_outcome"]
        history = partners[index].get("status_history", "")
        partners[index]["status_history"] = f"{history}|meeting_{outcome}:{now}" if history else f"meeting_{outcome}:{now}"
        status_map = {
            "scheduled": "meeting_scheduled",
            "completed": "meeting_completed",
            "offer":     "offer_received",
            "pass":      "archived:rejected"
        }
        if outcome in status_map:
            partners[index]["status"] = status_map[outcome]

    # Scratchpad notes
    if "notes" in data:
        partners[index]["notes"] = data["notes"]

    # Tags
    if "tags" in data:
        partners[index]["tags"] = "|".join(data["tags"])

    # Email content
    if "email_content" in data:
        save_email_body(partners[index].get("email_file", ""), data["email_content"])

    save_partners(partners)
    return jsonify(serialize_partner(partners[index], index))


@app.route("/api/partners/<int:index>/contacts", methods=["POST"])
def add_contact(index):
    partners = load_partners()
    if index < 0 or index >= len(partners):
        return jsonify({"error": "Not found"}), 404
    try:
        contacts = json.loads(partners[index].get("contacts", "[]") or "[]")
    except Exception:
        contacts = []
    data = request.json
    contacts.append({
        "name":       data.get("name", ""),
        "title":      data.get("title", ""),
        "email":      data.get("email", ""),
        "notes":      data.get("notes", ""),
        "date_added": datetime.now().strftime("%Y-%m-%d")
    })
    partners[index]["contacts"] = json.dumps(contacts)
    save_partners(partners)
    return jsonify(contacts)


@app.route("/api/partners/<int:index>/contacts/<int:contact_index>", methods=["DELETE"])
def remove_contact(index, contact_index):
    partners = load_partners()
    if index < 0 or index >= len(partners):
        return jsonify({"error": "Not found"}), 404
    try:
        contacts = json.loads(partners[index].get("contacts", "[]") or "[]")
        if 0 <= contact_index < len(contacts):
            contacts.pop(contact_index)
        partners[index]["contacts"] = json.dumps(contacts)
        save_partners(partners)
        return jsonify(contacts)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/partners/<int:index>/reply", methods=["POST"])
def send_reply(index):
    partners = load_partners()
    if index < 0 or index >= len(partners):
        return jsonify({"error": "Not found"}), 404
    data = request.json
    body = data.get("body", "")
    partner = partners[index]
    try:
        from src.gmail.gmail_client import get_gmail_service, send_email
        service = get_gmail_service()
        subject = f"Re: Amazon Connect Developer — Exploring Opportunities at {partner['name']}"
        send_email(service, partner.get("contact_email", ""), subject, body)
        now = datetime.now().isoformat()
        partners[index]["status"] = "reply_sent"
        history = partners[index].get("status_history", "")
        partners[index]["status_history"] = f"{history}|reply_sent:{now}" if history else f"reply_sent:{now}"
        save_partners(partners)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/scan", methods=["POST"])
def scan_inbox():
    try:
        from src.gmail.monitor import run_monitor
        stats = run_monitor()
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/send_batch", methods=["POST"])
def send_batch():
    try:
        from src.gmail.sender import send_pending_batch
        result = send_pending_batch(batch_size=50)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/retry_batch", methods=["POST"])
def retry_batch():
    try:
        from src.gmail.monitor import send_fallback_emails
        result = send_fallback_emails(batch_size=50)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/send_thankyou", methods=["POST"])
def send_thankyou():
    try:
        from src.gmail.monitor import send_thankyou_batch
        result = send_thankyou_batch(batch_size=50)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/send_keepwarm", methods=["POST"])
def send_keepwarm():
    try:
        from src.gmail.monitor import send_keepwarm_batch
        result = send_keepwarm_batch(batch_size=50)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/archive_no_response", methods=["POST"])
def archive_no_response():
    try:
        data = request.json or {}
        days = data.get("days", 30)
        from src.gmail.monitor import archive_no_response as do_archive
        result = do_archive(days=days)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/export")
def export_csv():
    partners = load_partners()
    si = io.StringIO()
    if partners:
        writer = csv.DictWriter(si, fieldnames=list(partners[0].keys()))
        writer.writeheader()
        writer.writerows(partners)
    output = io.BytesIO()
    output.write(si.getvalue().encode("utf-8"))
    output.seek(0)
    filename = f"pipeline_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(output, mimetype="text/csv",
                     as_attachment=True, download_name=filename)


@app.route("/api/snapshot", methods=["POST"])
def snapshot():
    try:
        import shutil
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = PARTNERS_CLASSIFIED_FILE.replace(".csv", f"_snapshot_{timestamp}.csv")
        shutil.copy2(PARTNERS_CLASSIFIED_FILE, dst)
        return jsonify({"success": True, "file": dst})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(port=FLASK_PORT, debug=FLASK_DEBUG)
