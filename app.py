import csv
import os
import json
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file
from config import PARTNERS_CLASSIFIED_FILE, FLASK_PORT, FLASK_DEBUG
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
    now = datetime.now()
    total          = len(partners)
    sent           = sum(1 for p in partners if p.get("status") == "sent")
    pending        = sum(1 for p in partners if p.get("status") in ["scraped", "pending"] and p.get("classification") != "ignore")
    ignored        = sum(1 for p in partners if p.get("classification") == "ignore")
    meeting_req    = sum(1 for p in partners if p.get("status") == "meeting_requested")
    meeting_sched  = sum(1 for p in partners if p.get("status") == "meeting_scheduled")
    meeting_done   = sum(1 for p in partners if p.get("status") == "meeting_completed")
    apply_link     = sum(1 for p in partners if p.get("status") == "apply_link_received")
    needs_reply    = sum(1 for p in partners if p.get("status") == "needs_reply")
    reply_sent     = sum(1 for p in partners if p.get("status") == "reply_sent")
    keep_warm      = sum(1 for p in partners if p.get("status") == "keep_warm")
    offer          = sum(1 for p in partners if p.get("status") == "offer_received")
    rejected       = sum(1 for p in partners if p.get("status") == "archived:rejected")
    bad_email      = sum(1 for p in partners if p.get("status") == "archived:bad_email")
    no_response    = sum(1 for p in partners if p.get("status") == "archived:no_response")
    bounced        = sum(1 for p in partners if p.get("status") in ["bounce:retry_queued", "archived:bad_email"])
    retry_queued   = sum(1 for p in partners if p.get("status") == "bounce:retry_queued")
    thankyou_due   = sum(1 for p in partners if p.get("response_type") == "negative_no_fit" and not p.get("thankyou_sent"))
    keepwarm_due   = sum(1 for p in partners if p.get("response_type") == "negative_no_opening" and not p.get("keepwarm_sent"))

    # Next action counts
    next_actions = {}
    for p in partners:
        na = p.get("next_action", "")
        if na and na != "none":
            next_actions[na] = next_actions.get(na, 0) + 1

    # Meeting outcomes
    meeting_outcomes = {}
    for p in partners:
        notes = p.get("meeting_notes", "")
        if notes:
            for outcome in ["scheduled", "completed", "offer", "pass"]:
                if outcome in notes.lower():
                    meeting_outcomes[outcome] = meeting_outcomes.get(outcome, 0) + 1

    # Retry stats
    retry_1st = sum(1 for p in partners if p.get("status_history", "").count("sent_fallback") == 1)
    retry_2nd = sum(1 for p in partners if p.get("status_history", "").count("sent_fallback") == 2)
    retry_3rd = sum(1 for p in partners if p.get("status_history", "").count("sent_fallback") >= 3)

    # Response rate
    total_sent = sum(1 for p in partners if p.get("sent_at"))
    total_replied = sum(1 for p in partners if p.get("last_reply"))
    response_rate = round((total_replied / total_sent * 100), 1) if total_sent > 0 else 0

    # Avg days to response
    days_list = [int(p["response_rate_days"]) for p in partners
                 if p.get("response_rate_days") and p["response_rate_days"].isdigit()]
    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else 0

    # Due today
    due_today = []
    for p in partners:
        date_str = p.get("next_action_date", "")
        if date_str:
            try:
                due_dt = datetime.strptime(date_str, "%Y-%m-%d")
                if due_dt.date() <= now.date():
                    due_today.append(p.get("name", ""))
            except Exception:
                pass

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
        "due_today": due_today,
    }


@app.route("/")
def index():
    partners = load_partners()
    stats = get_stats(partners)
    filter_by = request.args.get("filter", "action")
    search = request.args.get("search", "").lower()
    tag_filter = request.args.get("tag", "").lower()

    filter_map = {
        "action":    lambda p: p.get("status") in ["meeting_requested", "apply_link_received", "needs_reply"],
        "meeting":   lambda p: p.get("status") in ["meeting_requested", "meeting_scheduled", "meeting_completed"],
        "apply":     lambda p: p.get("status") == "apply_link_received",
        "keep_warm": lambda p: p.get("status") == "keep_warm",
        "sent":      lambda p: p.get("status") == "sent",
        "bounced":   lambda p: p.get("status") in ["bounce:retry_queued", "archived:bad_email"],
        "rejected":  lambda p: p.get("status") == "archived:rejected",
        "pending":   lambda p: p.get("status") in ["scraped", "pending"] and p.get("classification") != "ignore",
        "ignored":   lambda p: p.get("classification") == "ignore",
        "archived":  lambda p: "archived" in p.get("status", ""),
        "due_today": lambda p: p.get("next_action_date", "") != "" and _is_due(p.get("next_action_date", "")),
        "all":       lambda p: True,
    }

    fn = filter_map.get(filter_by, filter_map["action"])
    filtered = [p for p in partners if fn(p)]

    if search:
        filtered = [p for p in filtered if search in p.get("name", "").lower()]

    if tag_filter:
        filtered = [p for p in filtered if tag_filter in (p.get("tags", "") or "").lower()]

    # Collect all tags for filter pills
    all_tags = set()
    for p in partners:
        for t in (p.get("tags", "") or "").split("|"):
            t = t.strip()
            if t:
                all_tags.add(t)

    # Activity log
    from src.gmail.monitor import get_activity_log
    activity = get_activity_log(20)

    return render_template("index.html",
        partners=filtered,
        stats=stats,
        filter_by=filter_by,
        search=search,
        tag_filter=tag_filter,
        all_tags=sorted(all_tags),
        activity=activity,
        total_shown=len(filtered)
    )


def _is_due(date_str: str) -> bool:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() <= datetime.now().date()
    except Exception:
        return False


@app.template_filter("is_due")
def is_due_filter(date_str: str) -> bool:
    return _is_due(date_str or "")


@app.route("/company/<int:index>")
def company_detail(index):
    partners = load_partners()
    if index < 0 or index >= len(partners):
        return "Not found", 404
    partner = partners[index]
    email_content = load_email_body(partner.get("email_file", ""))
    try:
        contacts = json.loads(partner.get("contacts", "[]") or "[]")
    except Exception:
        contacts = []
    tags = [t.strip() for t in (partner.get("tags", "") or "").split("|") if t.strip()]
    return render_template("company.html",
        partner=partner, email_content=email_content,
        contacts=contacts, tags=tags, index=index)


@app.route("/api/update_status", methods=["POST"])
def update_status():
    data = request.json
    idx = data.get("index")
    new_status = data.get("status")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    now = datetime.now().isoformat()
    partners[idx]["status"] = new_status
    history = partners[idx].get("status_history", "")
    partners[idx]["status_history"] = f"{history}|{new_status}:{now}" if history else f"{new_status}:{now}"
    save_partners(partners)
    return jsonify({"success": True})


@app.route("/api/update_next_action", methods=["POST"])
def update_next_action():
    data = request.json
    idx = data.get("index")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    partners[idx]["next_action"] = data.get("next_action", "")
    partners[idx]["next_action_date"] = data.get("next_action_date", "")
    save_partners(partners)
    return jsonify({"success": True})


@app.route("/api/update_meeting_notes", methods=["POST"])
def update_meeting_notes():
    data = request.json
    idx = data.get("index")
    notes = data.get("notes", "")
    outcome = data.get("outcome", "")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    partners[idx]["meeting_notes"] = notes
    if outcome:
        now = datetime.now().strftime("%Y-%m-%d")
        history = partners[idx].get("status_history", "")
        partners[idx]["status_history"] = f"{history}|meeting_{outcome}:{now}" if history else f"meeting_{outcome}:{now}"
        status_map = {
            "scheduled": "meeting_scheduled",
            "completed": "meeting_completed",
            "offer":     "offer_received",
            "pass":      "archived:rejected"
        }
        if outcome in status_map:
            partners[idx]["status"] = status_map[outcome]
    save_partners(partners)
    return jsonify({"success": True})


@app.route("/api/update_notes", methods=["POST"])
def update_notes():
    data = request.json
    idx = data.get("index")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    partners[idx]["notes"] = data.get("notes", "")
    save_partners(partners)
    return jsonify({"success": True})


@app.route("/api/add_tag", methods=["POST"])
def add_tag():
    data = request.json
    idx = data.get("index")
    tag = data.get("tag", "").strip().lower()
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    tags = [t.strip() for t in (partners[idx].get("tags", "") or "").split("|") if t.strip()]
    if tag and tag not in tags:
        tags.append(tag)
    partners[idx]["tags"] = "|".join(tags)
    save_partners(partners)
    return jsonify({"success": True, "tags": tags})


@app.route("/api/remove_tag", methods=["POST"])
def remove_tag():
    data = request.json
    idx = data.get("index")
    tag = data.get("tag", "").strip().lower()
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    tags = [t.strip() for t in (partners[idx].get("tags", "") or "").split("|") if t.strip() and t.strip() != tag]
    partners[idx]["tags"] = "|".join(tags)
    save_partners(partners)
    return jsonify({"success": True, "tags": tags})


@app.route("/api/add_contact", methods=["POST"])
def add_contact():
    data = request.json
    idx = data.get("index")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    try:
        contacts = json.loads(partners[idx].get("contacts", "[]") or "[]")
    except Exception:
        contacts = []
    contacts.append({
        "name":       data.get("name", ""),
        "title":      data.get("title", ""),
        "email":      data.get("email", ""),
        "notes":      data.get("notes", ""),
        "date_added": datetime.now().strftime("%Y-%m-%d")
    })
    partners[idx]["contacts"] = json.dumps(contacts)
    save_partners(partners)
    return jsonify({"success": True, "contacts": contacts})


@app.route("/api/remove_contact", methods=["POST"])
def remove_contact():
    data = request.json
    idx = data.get("index")
    contact_idx = data.get("contact_index")
    partners = load_partners()
    if idx is None or idx < 0 or idx >= len(partners):
        return jsonify({"error": "Invalid index"}), 400
    try:
        contacts = json.loads(partners[idx].get("contacts", "[]") or "[]")
        if 0 <= contact_idx < len(contacts):
            contacts.pop(contact_idx)
        partners[idx]["contacts"] = json.dumps(contacts)
        save_partners(partners)
        return jsonify({"success": True, "contacts": contacts})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


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


@app.route("/api/send_batch", methods=["POST"])
def send_batch():
    try:
        from src.gmail.sender import send_pending_batch
        result = send_pending_batch(batch_size=50)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/retry_batch", methods=["POST"])
def retry_batch():
    try:
        from src.gmail.monitor import send_fallback_emails
        result = send_fallback_emails(batch_size=50)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/send_thankyou", methods=["POST"])
def send_thankyou():
    try:
        from src.gmail.monitor import send_thankyou_batch
        result = send_thankyou_batch(batch_size=50)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/send_keepwarm", methods=["POST"])
def send_keepwarm():
    try:
        from src.gmail.monitor import send_keepwarm_batch
        result = send_keepwarm_batch(batch_size=50)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/archive_no_response", methods=["POST"])
def archive_no_response():
    try:
        data = request.json or {}
        days = data.get("days", 30)
        from src.gmail.monitor import archive_no_response as do_archive
        result = do_archive(days=days)
        return jsonify({"success": True, **result})
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


@app.route("/api/stats")
def api_stats():
    partners = load_partners()
    return jsonify(get_stats(partners))


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
        src = PARTNERS_CLASSIFIED_FILE
        dst = PARTNERS_CLASSIFIED_FILE.replace(".csv", f"_snapshot_{timestamp}.csv")
        shutil.copy2(src, dst)
        return jsonify({"success": True, "file": dst})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    app.run(port=FLASK_PORT, debug=FLASK_DEBUG)
